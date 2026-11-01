"""Verify and stage the supported user's own game files without running them."""
from contextlib import ExitStack
import ctypes
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

try:
    from .install_game import RawISO, disc_files, extract_cab_member, extract_zip
except ImportError:
    from install_game import RawISO, disc_files, extract_cab_member, extract_zip

CHECKSUMS = Path(__file__).with_name('game_checksums.json')
# CFBundleIdentifier of NFSMW.app (tools/package_app.py).
APP_BUNDLE_ID = 'local.nfsmw.native'
APP_GAME = ('Contents', 'Resources', 'game')
APP_GAME_UNUSABLE = ('The game inside {name} is missing or modified, so it cannot be reused. '
                     'Choose your original game copy.')
APP_GAME_OLD = ('{name} was built by an older NFSMW Builder, which left part of your game copy out of it. '
                'Choose your original game copy once to build the complete app.')
# Made again from the original files by every build (tools/install_game.py, tools/hq_variants.py),
# so a game folder's or an app's own copy is never taken over. Case-folded; a folder covers
# everything below it.
DERIVED = ('.nfsmw', 'install-manifest.json', 'scripts/nfsmostwanted.widescreenfix.ini',
           'scripts/nfsmostwanted.widescreenfix.tpk')
# macOS code, which never comes from the player's copy into the app (_macos_code): a folder
# with a bundle or package extension or a Contents/Info.plist inside is left out whole; a file
# with one of these extensions, a script (#!) or a Mach-O head is left out. Case-folded.
MACOS_BUNDLES = ('.app', '.appex', '.framework', '.bundle', '.plugin', '.kext', '.pkg', '.mpkg', '.workflow',
                 '.action', '.xpc', '.prefpane', '.saver', '.qlgenerator', '.mdimporter', '.scptd', '.wdgt',
                 '.component', '.systemextension')
MACOS_FILES = ('.command', '.tool', '.sh', '.bash', '.zsh', '.csh', '.ksh', '.fish', '.py', '.pl', '.rb', '.php',
               '.scpt', '.applescript', '.terminal', '.dylib', '.so', '.jar', '.pkg', '.mpkg')
MACH_O = {bytes.fromhex(magic) for magic in ('feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
QUARANTINE = b'com.apple.quarantine'
XATTR_NOFOLLOW = 0x0001


class AppGameError(ValueError):
    """An NFSMW.app was chosen, but the game inside it cannot be used."""


def app_game(path):
    """The game folder inside an NFSMW.app built earlier, or None when `path` is not an app.

    An app carries the installed tree: the original files (the seven the official patch
    replaces already at 1.3), the rest of the player's copy (extras) and everything the build
    derived from them (DERIVED). The original files are checked and staged exactly as for an
    installed game folder, and the extras against the inventory the build recorded in
    install-manifest.json; everything derived is built again from them and the pinned
    downloads, so nothing produced by an older Builder is reused.
    """
    path = Path(path)
    if path.suffix.casefold() != '.app' or path.is_symlink() or not path.is_dir():
        return None
    try:
        info = plistlib.loads((path / 'Contents/Info.plist').read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        info = None
    if not isinstance(info, dict) or info.get('CFBundleIdentifier') != APP_BUNDLE_ID:
        raise ValueError(f'{path.name} is not an NFSMW.app built by NFSMW Builder')
    game = path
    for part in APP_GAME:
        game = game / part
        if game.is_symlink():
            raise AppGameError(APP_GAME_UNUSABLE.format(name=path.name))
    if not game.is_dir():
        raise AppGameError(APP_GAME_UNUSABLE.format(name=path.name))
    return game


def _from_app(sources):
    """Sources with a single chosen NFSMW.app replaced by the game folder inside it."""
    if len(sources) == 1 and not sources[0].is_symlink():
        game = app_game(sources[0])
        if game is not None:
            return [game], True
    return sources, False


def _load_clonefile():
    if sys.platform != 'darwin':
        return None
    try:
        function = ctypes.CDLL(None, use_errno=True).clonefile
    except (OSError, AttributeError):
        return None
    function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
    function.restype = ctypes.c_int
    return function


_CLONEFILE = _load_clonefile()
CLONE_NOFOLLOW = 0x0001


def _load_xattr():
    if sys.platform != 'darwin':
        return None, None
    libc = ctypes.CDLL(None, use_errno=True)
    get, put = libc.getxattr, libc.setxattr
    get.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int)
    get.restype = ctypes.c_ssize_t
    put.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int)
    put.restype = ctypes.c_int
    return get, put


_GETXATTR, _SETXATTR = _load_xattr()


def quarantine(path):
    """The com.apple.quarantine value of `path` (not followed if a symlink), or None."""
    if _GETXATTR is None:
        return None
    name = os.fsencode(path)
    size = _GETXATTR(name, QUARANTINE, None, 0, 0, XATTR_NOFOLLOW)
    if size >= 0:
        buffer = ctypes.create_string_buffer(size)
        size = _GETXATTR(name, QUARANTINE, buffer, size, 0, XATTR_NOFOLLOW)
        if size >= 0:
            return buffer.raw[:size]
    number = ctypes.get_errno()
    if number in (errno.ENOATTR, errno.ENOTSUP):
        return None
    raise OSError(number, f'cannot read the quarantine of {path}: {os.strerror(number)}')


def set_quarantine(path, value):
    """Puts the quarantine `value` (from quarantine()) on `path`; None leaves it as it is."""
    if value is None:
        return
    if _SETXATTR is None or _SETXATTR(os.fsencode(path), QUARANTINE, value, len(value), 0, XATTR_NOFOLLOW):
        number = ctypes.get_errno() if _SETXATTR is not None else errno.ENOTSUP
        raise OSError(number, f'cannot keep the quarantine on {path}: {os.strerror(number)}')


def keep_quarantine(source, target):
    """After a plain copy of `source` (a file or a folder) to `target`: every item of the copy
    gets the quarantine its original has, exactly, or the copy fails. A download's quarantine
    must not get lost in a fallback copy of the player's game files."""
    source, target = Path(source), Path(target)
    pairs = [(source, target)]
    if source.is_dir() and not source.is_symlink():
        for directory, subdirs, names in os.walk(source):
            for name in subdirs + names:
                path = Path(directory) / name
                pairs.append((path, target / path.relative_to(source)))
    for original, copy in pairs:
        set_quarantine(copy, quarantine(original))


def copy_keeping_quarantine(source, target):
    """A plain copy of `source` (a file or a folder) with its extended attributes and its exact
    quarantine (keep_quarantine), for when an APFS clone is not possible."""
    result = subprocess.run(['/bin/cp', '-pR' if Path(source).is_dir() else '-p', str(source), str(target)],
                            capture_output=True, text=True)
    if result.returncode:
        raise OSError(f'could not copy {Path(source).name}: {result.stderr.strip()}')
    keep_quarantine(source, target)


def _clone(source, target):
    """An APFS clone when both are on one APFS volume, else a plain copy that keeps the
    quarantine (copy_keeping_quarantine).

    A clone takes no extra space and shares nothing writable: later changes to the copy
    never reach the source, so a chosen NFSMW.app is only ever read.
    """
    # Another volume or file system (EXDEV, ENOTSUP) falls back to copying; so does anything
    # else, and copying reports a real problem itself.
    if _CLONEFILE is None or _CLONEFILE(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW) != 0:
        copy_keeping_quarantine(source, target)
    # The staged copy is an ordinary writable data file: the game only reads it, never runs it.
    os.chmod(target, 0o644)


def _path(name):
    name = name.replace('\\', '/')
    parts = name.rstrip('/').split('/')
    if not parts or any(p in ('', '.', '..') for p in parts) or name.startswith('/') or ':' in name or '\0' in name:
        raise ValueError(f'unsafe payload path: {name!r}')
    return '/'.join(parts)


def _claim(seen, name, directory=False):
    parts = name.split('/')
    for n in range(1, len(parts) + 1):
        part = '/'.join(parts[:n])
        kind = 'directory' if n < len(parts) or directory else 'file'
        previous = seen.get(part.casefold())
        if previous and (previous != (part, kind) or kind == 'file'):
            raise ValueError(f'duplicate, case or file/directory collision: {part}')
        seen[part.casefold()] = (part, kind)


def _digest(stream):
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(1 << 20):
        size += len(block)
        digest.update(block)
    return {'size': size, 'sha256': digest.hexdigest()}


def _matches(actual, expected):
    return actual['size'] == expected['size'] and actual['sha256'] == expected['sha256']


def _verified(stream, expected, name):
    actual = _digest(stream)
    if not _matches(actual, expected):
        raise ValueError(f'unsupported size or checksum: {name}')
    return actual


def _variant(path, row):
    with path.open('rb') as stream:
        actual = _digest(stream)
    for variant in row['variants']:
        if _matches(actual, variant):
            return {'path': row['path'], **actual, 'variant': variant['kind']}
    raise ValueError(f'unsupported size or checksum: {row["path"]}')


def _profile(data):
    if data is None:
        data = json.loads(CHECKSUMS.read_text())
    if data.get('schema_version') != 1:
        raise ValueError('unsupported game checksum profile')
    files = {}
    seen = {}
    for row in data['files']:
        name = _path(row['path'])
        if name != row['path']:
            raise ValueError('non-normalized checksum path')
        _claim(seen, name)
        if not row['variants']:
            raise ValueError(f'missing checksum: {name}')
        for variant in row['variants']:
            if not isinstance(variant['size'], int) or variant['size'] < 0 or not re.fullmatch('[0-9a-f]{64}', variant['sha256']):
                raise ValueError(f'invalid checksum: {name}')
        files[name.casefold()] = row
    archives = {row['role']: row for row in data['archives']}
    if set(archives) != set(range(4)) or len(data['archives']) != 4:
        raise ValueError('checksum profile must describe four disc roles')
    return data, files, archives


def _folder_files(root):
    files, seen = {}, {}
    for directory, subdirs, names in os.walk(root, followlinks=False):
        for name in subdirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f'source symlink refused: {name}')
            relative = _path(path.relative_to(root).as_posix())
            is_directory = path.is_dir()
            if not is_directory and not path.is_file():
                raise ValueError(f'unsupported source file: {relative}')
            _claim(seen, relative, is_directory)
            if not is_directory:
                files[relative.casefold()] = path
    return files


def _cue(path):
    if path.stat().st_size > 65536:
        raise ValueError('CUE exceeds the single-track description limit')
    try:
        text = path.read_text(encoding='utf-8-sig')
    except UnicodeError as error:
        raise ValueError('CUE must contain a plain text single-track description') from error
    filename = mode = None
    indices = []
    for line in text.splitlines():
        line = line.strip()
        if not line or re.match(r'REM(?:\s|$)', line, re.I):
            continue
        match = re.fullmatch(r'FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY', line, re.I)
        if match:
            if filename is not None or mode is not None:
                raise ValueError('CUE requires exactly one FILE and one TRACK 01')
            filename = match[1] or match[2]
            continue
        match = re.fullmatch(r'TRACK\s+01\s+(MODE1/(?:2048|2352))', line, re.I)
        if match and filename is not None and mode is None:
            mode = match[1].upper()
            continue
        match = re.fullmatch(r'INDEX\s+(00|01)\s+00:00:00', line, re.I)
        if match and mode is not None and match[1] not in indices:
            indices.append(match[1])
            continue
        raise ValueError('CUE supports only one TRACK 01 MODE1/2048 or MODE1/2352 with zero indices')
    if filename is None or mode is None or indices not in (['01'], ['00', '01']):
        raise ValueError('CUE requires one FILE, TRACK 01 and INDEX 01 00:00:00')
    try:
        name = _path(filename)
    except ValueError as error:
        raise ValueError('CUE FILE must be a relative path within its directory') from error
    binary = path.parent
    for part in PurePosixPath(name).parts:
        binary = binary / part
        if binary.is_symlink():
            raise ValueError('CUE symlink reference refused')
    if not binary.is_file() or not binary.resolve().is_relative_to(path.parent.resolve()):
        raise ValueError('CUE referenced image is absent or escapes its directory')
    with RawISO(binary) as image:
        if image.raw != (mode == 'MODE1/2352'):
            raise ValueError('CUE track mode does not match the actual image sector layout')
    return binary


def _images(inputs):
    images, identities = [], set()
    for path in inputs:
        if path.is_symlink():
            raise ValueError('source image symlink refused')
        if not path.is_file():
            raise ValueError('expected ISO, BIN or single-track CUE source files')
        if path.suffix.casefold() == '.cue':
            path = _cue(path)
        elif path.suffix.casefold() not in ('.iso', '.bin'):
            raise ValueError('expected ISO, BIN or single-track CUE source files')
        identity = path.resolve()
        if identity not in identities:
            identities.add(identity)
            images.append(path)
    return images


def _disc_inventory(images, archives):
    roles = {}
    for image in images:
        entries, seen, index = disc_files(image), {}, {}
        for entry in entries:
            name = _path(entry.name)
            _claim(seen, name)
            index[name.casefold()] = entry
        found = [role for role, row in archives.items() if row['path'].casefold() in index]
        if len(found) != 1:
            raise ValueError('each disc image must contain exactly one 0compressed.zip..3compressed.zip role')
        role = found[0]
        if role in roles:
            raise ValueError(f'duplicate disc archive role: {role}')
        entry = index[archives[role]['path'].casefold()]
        if entry.size != archives[role]['size']:
            raise ValueError(f'unsupported archive size: {archives[role]["path"]}')
        with RawISO(image, entry.offset, entry.size) as stream:
            _verified(stream, archives[role], archives[role]['path'])
        roles[role] = (image, index, entry)
    if set(roles) != set(archives):
        raise ValueError('missing disc roles; supply all four game images')
    return roles


def _directories(files):
    directories = {}
    for row in files.values():
        parts = row['path'].split('/')
        for count in range(1, len(parts)):
            name = '/'.join(parts[:count])
            directories[name.casefold()] = name
    return directories


def _members(archive, role, files, archives, seen, directories, found):
    """Check one disc ZIP's directory against the profile and normalize its member names."""
    for info in archive.infolist():
        name = _path(info.orig_filename)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f'ZIP symlink refused: {name}')
        directory = info.is_dir() or info.filename.endswith('\\')
        _claim(seen, name, directory)
        if directory:
            if name.casefold() not in directories:
                raise ValueError(f'unexpected ZIP directory: {name}')
            info.filename = directories[name.casefold()] + '/'
            continue
        row = files.get(name.casefold())
        if not row or row['source'].get('archive') != archives[role]['path'] or row['source'].get('role') != role:
            raise ValueError(f'unexpected ZIP member for disc role {role}: {name}')
        if info.file_size not in {v['size'] for v in row['variants']}:
            raise ValueError(f'unsupported ZIP member size: {name}')
        found.add(name.casefold())
        # ZipFile validates the stored header using orig_filename, not filename.
        info.filename = row['path']


def _extract_discs(images, destination, profile, files, archives):
    roles = _disc_inventory(images, archives)
    seen, found, directories = {}, set(), _directories(files)
    with ExitStack() as stack:
        opened = []
        for role in sorted(roles):
            image, index, entry = roles[role]
            raw = stack.enter_context(RawISO(image, entry.offset, entry.size))
            stream = stack.enter_context(io.BufferedReader(raw))
            archive = stack.enter_context(zipfile.ZipFile(stream))
            _members(archive, role, files, archives, seen, directories, found)
            opened.append(archive)
        expected = {key for key, row in files.items() if 'archive' in row['source']}
        if found != expected:
            raise ValueError('missing required ZIP payload members')
        cab = profile['d3dx_cab']
        cab_image, cab_index, _ = roles[cab['role']]
        cab_entry = cab_index.get(cab['path'].casefold())
        if cab_entry is None:
            raise ValueError(f'required D3DX cabinet absent: {cab["path"]}')
        with RawISO(cab_image, cab_entry.offset, cab_entry.size) as stream:
            _verified(stream, cab, cab['path'])
        # Root files cannot overwrite any archive member, even via path casing.
        roots = []
        for row in files.values():
            source = row['source']
            if row['path'].casefold() == 'd3dx9_26.dll' or 'disc_path' not in source:
                continue
            image, index, _ = roles[source['role']]
            entry = index.get(source['disc_path'].casefold())
            if entry is None:
                raise ValueError(f'required disc root file absent: {row["path"]}')
            _claim(seen, row['path'])
            roots.append((row, image, entry))
        # Every file written from a disc image gets the image's quarantine (a downloaded image
        # keeps macOS's check on what came out of it), as an APFS clone of a folder keeps it.
        for role, archive in zip(sorted(roles), opened):
            extract_zip(archive, destination)
            mark = quarantine(roles[role][0])
            for info in archive.infolist():
                set_quarantine(destination / info.filename.rstrip('/'), mark)
        for row, image, entry in roots:
            target = destination / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            with RawISO(image, entry.offset, entry.size) as stream, target.open('wb') as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            set_quarantine(target, quarantine(image))
        with tempfile.TemporaryDirectory(prefix='nfsmw-cab-') as temporary:
            cabinet = Path(temporary) / 'directx.cab'
            with RawISO(cab_image, cab_entry.offset, cab_entry.size) as stream, cabinet.open('wb') as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            (destination / 'd3dx9_26.dll').write_bytes(extract_cab_member(cabinet, 'd3dx9_26.dll'))
            set_quarantine(destination / 'd3dx9_26.dll', quarantine(cab_image))
        extras = _disc_extras(roles, archives, files, destination, seen)
    return [{'role': role, 'archive': archives[role]['path'],
             'size': archives[role]['size'], 'sha256': archives[role]['sha256']} for role in sorted(roles)], extras


def _disc_extras(roles, archives, files, destination, seen):
    """Write every other file of the discs into `destination` (AutoRun, DirectX, Support and
    the other Windows-only extras), less Finder files and macOS code. The four archives stay
    out: they are the installer's packed copy of the game files, which are in `destination`
    unpacked. A name on several discs is written once; a different copy on a later disc goes
    into a folder named after that disc, such as Disc 2/bin.dat. -> the relative paths written."""
    written, extras = {}, []
    for role in sorted(roles):
        image, index, _ = roles[role]
        bundles, logged, mark = _macos_bundles(index), set(), quarantine(image)
        for key, item in sorted(index.items()):
            name = _path(item.name)
            if key == archives[role]['path'].casefold() or _finder_file(name):
                continue
            with RawISO(image, item.offset, item.size) as stream:
                head = stream.read(4)
            left_out = _macos_code(name, head, bundles)
            if left_out:
                if left_out not in logged:
                    print(f'left out of the app (macOS code): Disc {role + 1}: {left_out}', flush=True)
                logged.add(left_out)
                continue
            with RawISO(image, item.offset, item.size) as stream:
                found = _digest(stream)
            if key in files or key in written:
                if key in files and files[key]['source'].get('disc_path', '').casefold() == key \
                        and files[key]['source'].get('role') == role:
                    continue  # staged as a game file
                staged = destination / (files[key]['path'] if key in files else written[key])
                with staged.open('rb') as stream:
                    if _matches(_digest(stream), found):
                        continue
                name = f'Disc {role + 1}/{name}'
                key = name.casefold()
            try:
                _claim(seen, name)
            except ValueError:
                print(f'left out of the app (it clashes with a game file): Disc {role + 1}: {name}', flush=True)
                continue
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with RawISO(image, item.offset, item.size) as stream, target.open('wb') as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            set_quarantine(target, mark)
            written[key] = name
            extras.append(name)
    return extras


REQUIRED_RELEASE = ('Need for Speed Most Wanted (2005) for PC, USA English Black Edition (4 CDs), '
                    'original or updated to v1.3')
NOT_SUPPORTED = ['other regions', 'the DVD edition', 'Most Wanted (2012)', 'console versions',
                 'repacks or modified copies']
VERSIONS = {'source': 'USA English Black Edition, original discs (updated to 1.3 during the build)',
            'official-1.3': 'USA English Black Edition, updated to 1.3',
            'canonical': 'A game folder prepared by an earlier build'}
EXECUTABLE_LABELS = {'source': 'Original disc executable', 'official-1.3': 'Official 1.3 executable'}


def _accepted(row):
    return [{'kind': v['kind'], 'size': v['size'], 'sha256': v['sha256']} for v in row['variants']]


def _is_image(path):
    return path.suffix.casefold() in ('.iso', '.bin', '.cue')


def _layout(sources):
    """Folder or disc input, decided exactly like stage_game."""
    if len(sources) == 1 and sources[0].is_dir() and not sources[0].is_symlink():
        root = sources[0]
        names = list(root.iterdir())
        images = sorted(path for path in names if _is_image(path))
        if not any(path.name.casefold() == 'speed.exe' for path in names):
            return ('discs', images) if images else ('none', [])
        return 'folder', [root]
    return 'discs', sources


def _finder_file(relative):
    return any(part == '.DS_Store' or part.startswith('._') or part == '__MACOSX' for part in relative.split('/'))


def _derived(key):
    return any(key == name or key.startswith(name + '/') for name in DERIVED)


def _macos_bundles(keys):
    """The folders among `keys` (the case-folded relative paths of a copy's files) that are macOS
    bundles or packages: a name with a bundle extension, or a Contents/Info.plist inside."""
    bundles = set()
    for key in keys:
        parts = key.split('/')
        for count in range(1, len(parts)):
            if parts[count - 1].endswith(MACOS_BUNDLES):
                bundles.add('/'.join(parts[:count]))
        if len(parts) > 2 and parts[-2:] == ['contents', 'info.plist']:
            bundles.add('/'.join(parts[:-2]))
    return bundles


def _macos_code(relative, head, bundles):
    """No macOS code from the player's copy goes into the app: the game is Windows files only,
    and a Mac program hidden in a downloaded copy must not end up inside a signed app.
    -> what is left out for `relative` (a file with the first bytes `head`): the bundle it is in
    (_macos_bundles), the file itself, or None when it is not macOS code."""
    parts = relative.split('/')
    for count in range(1, len(parts)):
        if '/'.join(parts[:count]).casefold() in bundles:
            return '/'.join(parts[:count])
    if parts[-1].casefold().endswith(MACOS_FILES) or head[:2] == b'#!' or head[:4] in MACH_O:
        return relative
    return None


def _folder_extras(root, available, files, log=False):
    """Everything in the game folder `root` (its _folder_files() `available`) besides the
    profiled and derived files: the Windows-only extras of the player's copy, less Finder files
    and macOS code. -> [(relative, path)]."""
    extras, bundles, logged = [], _macos_bundles(available), set()
    for key, path in sorted(available.items()):
        relative = _path(path.relative_to(root).as_posix())
        if key in files or _derived(key) or _finder_file(relative):
            continue
        with path.open('rb') as stream:
            head = stream.read(4)
        left_out = _macos_code(relative, head, bundles)
        if left_out:
            if log and left_out not in logged:
                print(f'left out of the app (macOS code): {left_out}', flush=True)
            logged.add(left_out)
            continue
        extras.append((relative, path))
    return extras


def _inventory(pairs):
    """Files, bytes and an aggregate SHA-256 of (relative, path) pairs: sorted case-folded paths,
    each followed by NUL and the file's raw SHA-256 digest."""
    aggregate, size, rows = hashlib.sha256(), 0, []
    for relative, path in pairs:
        with path.open('rb') as stream:
            rows.append((relative.casefold(), _digest(stream)))
    for key, row in sorted(rows):
        aggregate.update(key.encode('utf-8') + b'\0' + bytes.fromhex(row['sha256']))
        size += row['size']
    return {'files': len(rows), 'bytes': size, 'sha256': aggregate.hexdigest()}


def _recorded_extras(game):
    """The extras inventory an app's build recorded, or None (an app from an older Builder)."""
    try:
        manifest = json.loads((Path(game) / 'install-manifest.json').read_text())
        extras = manifest['source']['extras']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return extras if isinstance(extras, dict) else None


def _check_folder(root, files, report, add):
    available = _folder_files(root)
    for key, row in files.items():
        if row['required']:
            report['checked'] += 1
        source = available.get(key)
        if source is None:
            if row['required']:
                add(row['path'], 'missing', row)
            continue
        with source.open('rb') as stream:
            actual = _digest(stream)
        variant = next((v['kind'] for v in row['variants'] if _matches(actual, v)), None)
        if variant is None:
            add(row['path'], actual, row)
        elif row['path'] == 'speed.exe':
            report['version'] = VERSIONS.get(variant)


def _check_discs(sources, profile, files, archives, report, add):
    def invalid(path, error):
        text = str(error)
        report['invalid'].append(text if text.startswith(path.name) else f'{path.name}: {text}')

    images, identities = [], set()
    for path in sources:
        if not path.exists():
            report['invalid'].append(f'{path.name} does not exist')
            continue
        try:
            image = _images([path])[0]
        except ValueError as error:
            invalid(path, error)
            continue
        if image.resolve() not in identities:
            identities.add(image.resolve())
            images.append((path, image))
    roles = {}
    for path, image in images:
        try:
            index, seen = {}, {}
            for entry in disc_files(image):
                name = _path(entry.name)
                _claim(seen, name)
                index[name.casefold()] = entry
        except ValueError as error:
            invalid(path, error)
            continue
        found = [role for role, row in archives.items() if row['path'].casefold() in index]
        if len(found) != 1:
            report['invalid'].append(f'{path.name} is not one of the four supported discs: it has no '
                                     'single 0compressed.zip to 3compressed.zip archive')
            continue
        role = found[0]
        if role in roles:
            report['invalid'].append(f'{path.name} is a second copy of disc {role + 1}')
            continue
        row, entry = archives[role], index[archives[role]['path'].casefold()]
        with RawISO(image, entry.offset, entry.size) as stream:
            actual = _digest(stream)
        if not _matches(actual, row):
            report['wrong'].append({'name': path.name, 'archive': row['path']})
            add(f'Disc {role + 1}: {row["path"]}', actual, {'variants': [{'kind': 'disc', **row}]})
            continue
        roles[role] = (path, image, index, entry)
    report['discs'] = {'found': sorted(roles), 'missing': sorted(set(archives) - set(roles))}
    seen, members, directories = {}, set(), _directories(files)
    for role in sorted(roles):
        path, image, index, entry = roles[role]
        try:
            with RawISO(image, entry.offset, entry.size) as raw, io.BufferedReader(raw) as stream, \
                    zipfile.ZipFile(stream) as archive:
                _members(archive, role, files, archives, seen, directories, members)
        except (ValueError, zipfile.BadZipFile) as error:
            report['invalid'].append(f'{path.name} is not one of the four supported discs: {error}')
    if report['discs']['missing'] or report['invalid'] or report['wrong']:
        return
    expected = {key for key, row in files.items() if 'archive' in row['source']}
    if members != expected:
        report['invalid'].append('the disc archives do not hold every required game file')
    cab = profile['d3dx_cab']
    _, image, index, _ = roles[cab['role']]
    entry = index.get(cab['path'].casefold())
    report['checked'] += 1
    if entry is None:
        add(f'Disc {cab["role"] + 1}: {cab["path"]}', 'missing', {'variants': [{'kind': 'disc', **cab}]})
    else:
        with RawISO(image, entry.offset, entry.size) as stream:
            actual = _digest(stream)
        if not _matches(actual, cab):
            add(f'Disc {cab["role"] + 1}: {cab["path"]}', actual, {'variants': [{'kind': 'disc', **cab}]})
    for row in files.values():
        source = row['source']
        if 'disc_path' not in source or row['path'].casefold() == 'd3dx9_26.dll':
            continue
        # stage_game copies every disc root file it knows, optional ones included.
        report['checked'] += 1
        _, image, index, _ = roles[source['role']]
        entry = index.get(source['disc_path'].casefold())
        if entry is None:
            add(row['path'], 'missing', row)
            continue
        with RawISO(image, entry.offset, entry.size) as stream:
            actual = _digest(stream)
        if not any(_matches(actual, v) for v in row['variants']):
            add(row['path'], actual, row)
    report['checked'] += len(archives)


def check_sources(sources, *, profile=None, limit=20):
    """Check a game copy like stage_game, without writing anywhere, and collect every problem.

    Returns a JSON-ready report: ok, kind (folder, discs or none), version, checked and
    failed counts (kind app: the game inside a chosen NFSMW.app), the first `limit` problems in detail, the disc roles found and missing,
    and the plain message from describe().
    """
    profile, files, archives = _profile(profile)
    sources = [Path(source) for source in sources]
    report = {'ok': False, 'kind': 'none', 'app': None, 'version': None, 'checked': 0, 'failed': 0, 'problems': [],
              'discs': None, 'invalid': [], 'wrong': [], 'message': ''}

    def add(path, found, row):
        report['failed'] += 1
        if len(report['problems']) < limit:
            report['problems'].append({'path': path, 'found': found, 'accepted': _accepted(row)})

    try:
        if not sources:
            raise ValueError('no game copy was chosen')
        for source in sources:
            if source.is_symlink():
                raise ValueError(f'{source.name} is a symbolic link; choose the original file or folder')
        report['app'] = sources[0].name if len(sources) == 1 and app_game(sources[0]) is not None else None
        sources, _ = _from_app(sources)
        if report['app'] and not any(path.name.casefold() == 'speed.exe' for path in sources[0].iterdir()):
            raise AppGameError(APP_GAME_UNUSABLE.format(name=report['app']))
        kind, inputs = _layout(sources)
        report['kind'] = kind
        if kind == 'folder':
            _check_folder(inputs[0], files, report, add)
            if report['app']:
                recorded = _recorded_extras(inputs[0])
                if recorded is None:
                    raise AppGameError(APP_GAME_OLD.format(name=report['app']))
                found = _inventory(_folder_extras(inputs[0], _folder_files(inputs[0]), files))
                if found != recorded:
                    raise AppGameError(APP_GAME_UNUSABLE.format(name=report['app']))
        elif kind == 'discs':
            _check_discs(inputs, profile, files, archives, report, add)
            if not report['invalid'] and not report['wrong'] and not report['discs']['missing']:
                report['version'] = 'USA English Black Edition, 4 CDs'
    except AppGameError as error:
        report['app'] = report.get('app') or sources[0].name
        report['invalid'].append(str(error))
    except (ValueError, OSError) as error:
        report['invalid'].append(str(error))
    missing = (report['discs'] or {}).get('missing')
    report['ok'] = report['kind'] != 'none' and not (report['failed'] or report['invalid'] or report['wrong'] or missing)
    if report.get('app') and report['kind'] in ('folder', 'none'):
        report['kind'] = 'app'
    report['message'] = describe(report)
    return report


def _names(items):
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' and ' + items[-1]


def describe(report):
    """The plain sentence the Builder shows for a checked copy."""
    if report['ok']:
        return report['version'] or 'Supported game copy'
    if report.get('app'):
        old = APP_GAME_OLD.format(name=report['app'])
        return old if old in report['invalid'] else APP_GAME_UNUSABLE.format(name=report['app'])
    prefix = 'This is not the supported game copy. NFSMW Builder needs ' + REQUIRED_RELEASE + '. '
    discs = report.get('discs') or {}
    if report['kind'] == 'none' and not report['invalid']:
        return prefix + 'This folder has no speed.exe and no disc images.'
    if report['wrong']:
        wrong = report['wrong'][0]
        return (prefix + f'{wrong["name"]} is not one of the four supported discs: its {wrong["archive"]} '
                'has a different size or checksum.')
    if report['invalid']:
        text = report['invalid'][0]
        return prefix + text[:1].upper() + text[1:] + '.'
    if discs.get('missing'):
        found, missing = len(discs['found']), discs['missing']
        if found and len(missing) == 1:
            role = missing[0]
            return (prefix + f'Found {found} of the 4 discs. Disc {role + 1} (the image that contains '
                    f'{role}compressed.zip) is missing.')
        return (prefix + f'Found {found} of the 4 discs. Choose all four disc images together, '
                'or a folder that contains them.')
    shown = [problem['path'] for problem in report['problems'][:3]]
    verb = 'is' if report['failed'] == 1 else 'are'
    return (prefix + f'{report["failed"]:,} of {report["checked"]:,} files {verb} missing or different, '
            f'for example {_names(shown)}.')


def accepted_copies(profile=None):
    """What the Builder accepts, computed from the checksum profile."""
    profile, files, archives = _profile(profile)
    required = [row for row in files.values() if row['required']]

    def total(kinds):
        return sum(next(v['size'] for kind in kinds for v in row['variants'] if v['kind'] == kind)
                   for row in required)

    executable = files['speed.exe']
    return {'release': REQUIRED_RELEASE, 'not_supported': list(NOT_SUPPORTED),
            'discs': [{'disc': role + 1, 'archive': row['path'], 'size': row['size'], 'sha256': row['sha256']}
                      for role, row in sorted(archives.items())],
            'discs_total': sum(row['size'] for row in archives.values()),
            'folder': {'required_files': len(required), 'total_original': total(['source']),
                       'total_official': total(['official-1.3', 'source']),
                       'executables': [{'kind': v['kind'], 'label': EXECUTABLE_LABELS[v['kind']],
                                        'size': v['size'], 'sha256': v['sha256']}
                                       for v in executable['variants'] if v['kind'] in EXECUTABLE_LABELS]}}


def stage_game(sources, destination, *, profile=None):
    """Stage verified payload files, and the rest of the copy beside them (its extras, recorded
    in the returned manifest), into an existing empty caller-owned directory.

    The optional checksum profile is for small internal fixtures, not a CLI bypass.
    Failure may leave partial staging files; inputs are always read-only.
    """
    destination = Path(destination)
    if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
        raise FileExistsError('staging destination must be an existing empty directory')
    profile, files, archives = _profile(profile)
    sources = [Path(source) for source in sources]
    if not sources or any(source.is_symlink() for source in sources):
        raise ValueError('supply game sources without symlinks')
    app_name = sources[0].name if sources else ''
    sources, from_app = _from_app(sources)
    folder = len(sources) == 1 and sources[0].is_dir()
    if folder:
        root = sources[0]
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError('staging destination must be outside the source directory')
        images = [path for path in root.iterdir() if path.suffix.casefold() in ('.iso', '.bin', '.cue')]
        if not any(path.name.casefold() == 'speed.exe' for path in root.iterdir()) and images and not from_app:
            sources = images
            folder = False
    manifest = {'schema_version': 1, 'profile': profile['profile'],
                'source_kind': 'folder' if folder else 'discs', 'archives': [], 'files': []}
    if folder:
        available = _folder_files(sources[0])
        chosen = []
        for key, row in files.items():
            source = available.get(key)
            if source is None:
                if row['required']:
                    raise ValueError(f'missing required game file: {row["path"]}')
                continue
            _variant(source, row)
            chosen.append((source, row))
        for source, row in chosen:
            target = destination / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            _clone(source, target)
        # The rest of the copy goes in as it is (APFS clones keep a download's quarantine).
        extras, directories = [], _directories(files)
        for relative, source in _folder_extras(sources[0], available, files, log=True):
            # In a game folder, under its usual name (GLOBAL, not global), on every file system.
            parts = relative.split('/')
            for count in range(len(parts) - 1, 0, -1):
                known = directories.get('/'.join(parts[:count]).casefold())
                if known:
                    relative = '/'.join([known, *parts[count:]])
                    break
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _clone(source, target)
            extras.append(relative)
    else:
        manifest['archives'], extras = _extract_discs(_images(sources), destination, profile, files, archives)
    manifest['extras'] = _inventory((relative, destination / relative) for relative in extras)
    if from_app:
        recorded = _recorded_extras(sources[0])
        if recorded is None:
            raise AppGameError(APP_GAME_OLD.format(name=app_name))
        if recorded != manifest['extras']:
            raise AppGameError(APP_GAME_UNUSABLE.format(name=app_name))
    for row in files.values():
        staged = destination / row['path']
        if staged.is_file():
            manifest['files'].append(_variant(staged, row))
        elif row['required']:
            raise ValueError(f'missing required staged game file: {row["path"]}')
    return manifest
