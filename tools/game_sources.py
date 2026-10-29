"""Verify and stage the supported user's own game files without running them."""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

try:
    from .install_game import RawISO, disc_files, extract_zip
except ImportError:
    from install_game import RawISO, disc_files, extract_zip

CHECKSUMS = Path(__file__).with_name('game_checksums.json')


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


def _extract_discs(images, destination, profile, files, archives):
    roles = _disc_inventory(images, archives)
    seen, found, directories = {}, set(), {}
    for row in files.values():
        parts = row['path'].split('/')
        for count in range(1, len(parts)):
            name = '/'.join(parts[:count])
            directories[name.casefold()] = name
    with ExitStack() as stack:
        opened = []
        for role in sorted(roles):
            image, index, entry = roles[role]
            raw = stack.enter_context(RawISO(image, entry.offset, entry.size))
            stream = stack.enter_context(io.BufferedReader(raw))
            archive = stack.enter_context(zipfile.ZipFile(stream))
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
        for archive in opened:
            extract_zip(archive, destination)
        for row, image, entry in roots:
            target = destination / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            with RawISO(image, entry.offset, entry.size) as stream, target.open('wb') as output:
                shutil.copyfileobj(stream, output, 1 << 20)
        with tempfile.TemporaryDirectory(prefix='nfsmw-cab-') as temporary:
            cabinet = Path(temporary) / 'directx.cab'
            with RawISO(cab_image, cab_entry.offset, cab_entry.size) as stream, cabinet.open('wb') as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            result = subprocess.run(['cabextract', '-p', '-F', 'd3dx9_26.dll', str(cabinet)], capture_output=True)
            if result.returncode:
                raise ValueError('cabextract could not decode the required x86 D3DX DLL')
            (destination / 'd3dx9_26.dll').write_bytes(result.stdout)
    return [{'role': role, 'archive': archives[role]['path'],
             'size': archives[role]['size'], 'sha256': archives[role]['sha256']} for role in sorted(roles)]


def stage_game(sources, destination, *, profile=None):
    """Stage verified payload files into an existing empty caller-owned directory.

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
    folder = len(sources) == 1 and sources[0].is_dir()
    if folder:
        root = sources[0]
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError('staging destination must be outside the source directory')
        images = [path for path in root.iterdir() if path.suffix.casefold() in ('.iso', '.bin', '.cue')]
        if not any(path.name.casefold() == 'speed.exe' for path in root.iterdir()) and images:
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
            shutil.copyfile(source, target)
    else:
        manifest['archives'] = _extract_discs(_images(sources), destination, profile, files, archives)
    for row in files.values():
        staged = destination / row['path']
        if staged.is_file():
            manifest['files'].append(_variant(staged, row))
        elif row['required']:
            raise ValueError(f'missing required staged game file: {row["path"]}')
    return manifest
