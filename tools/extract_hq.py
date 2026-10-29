"""Extract the supplied HQ package with a native innoextract binary, without running setup."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

# The known HQ 1.20.9 installer. Redist files are deliberately never executed.
INSTALLER_SHA256 = '5762826eed51d358d4674a05d5b0f451c46535f862ddb922faa61a9d1f4b4683'
INSTALLER_MEMBERS = {'setup.exe': 3036497, 'setup-1.bin': 1854627328, 'setup-2.bin': 1328346461}
SLICE_SHA256 = {
    'setup-1.bin': '37a465415949440d13419809b32ca4ec1512468aa49418f94e70c2ae81af030b',
    'setup-2.bin': 'bc1a2c149cf504aba70a2aef7551878e6af22fdf56a09b1994a0793361f4e8cb',
}
SUFFIX = re.compile(r'[$#@].*$')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_relative(name):
    name = name.replace('\\', '/')
    parts = PurePosixPath(name).parts
    if not parts or name.startswith('/') or '..' in parts or ':' in name or '\0' in name:
        raise ValueError(f'unsafe HQ path: {name}')
    return PurePosixPath(*parts)


def normalize_payload(app, destination):
    """Collapse identical installer copies, preserving differing optional variants."""
    groups = {}
    for source in sorted(app.rglob('*')):
        if source.is_symlink():
            raise ValueError('HQ payload symlinks are unsupported')
        if not source.is_file():
            continue
        original = source.relative_to(app).as_posix()
        canonical = safe_relative(SUFFIX.sub('', original)).as_posix()
        relative = original.replace('\\', '-')
        safe_relative(relative)
        groups.setdefault(canonical.casefold(), []).append((relative, canonical, source, sha256(source)))
    files, variants = {}, {}
    for group in groups.values():
        canonical = group[0][1]
        hashes = {entry[3] for entry in group}
        if len(hashes) > 1 and any(not SUFFIX.search(entry[0]) for entry in group):
            raise ValueError(f'ambiguous HQ collision: {canonical}')
        selected = group[:1] if len(hashes) == 1 else group
        for relative, _, source, digest in selected:
            target = canonical if len(hashes) == 1 else relative
            output = destination.joinpath(*PurePosixPath(target).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, output)
            files[target] = {'size': source.stat().st_size, 'sha256': digest,
                             'installer_paths': [entry[0] for entry in group if entry[3] == digest]}
        if len(hashes) > 1:
            variants[canonical] = [entry[0] for entry in group]
    return {'files': files, 'variants': variants}


def extract_hq(archive: Path, destination: Path, extractor: Path) -> dict:
    """Return a manifest and publish normalized app files into a new destination.

    Different optional versions retain their $N names and appear in variants;
    callers must choose one explicitly before applying them to a game directory.
    No network access occurs. Build tools/build_hq_extractor.py explicitly first.
    """
    archive, destination, extractor = Path(archive), Path(destination), Path(extractor).resolve()
    if destination.exists():
        raise FileExistsError('HQ destination exists; keeping it untouched')
    if not extractor.is_file():
        raise FileNotFoundError('native innoextract missing; run tools/build_hq_extractor.py explicitly')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nfsmw-hq-', dir=destination.parent) as temporary:
        temporary = Path(temporary)
        installer = temporary / 'installer'
        installer.mkdir()
        with zipfile.ZipFile(archive) as zipped:
            seen = set()
            for info in zipped.infolist():
                relative = safe_relative(info.filename).as_posix()
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('HQ archive symlinks are unsupported')
                key = relative.casefold()
                if key in seen:
                    raise ValueError(f'duplicate HQ ZIP member: {relative}')
                seen.add(key)
            inputs = {}
            for name, size in INSTALLER_MEMBERS.items():
                info = zipped.getinfo(name)
                if info.file_size != size:
                    raise ValueError(f'unsupported HQ installer size: {name}')
                output = installer / name
                with zipped.open(info) as src, output.open('wb') as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                inputs[name] = {'size': size, 'sha256': sha256(output)}
                if name in SLICE_SHA256 and inputs[name]['sha256'] != SLICE_SHA256[name]:
                    raise ValueError(f'unsupported HQ slice SHA-256: {name}')
            if inputs['setup.exe']['sha256'] != INSTALLER_SHA256:
                raise ValueError('unsupported HQ setup.exe SHA-256')
        payload, staged = temporary / 'payload', temporary / 'normalized'
        staged.mkdir()
        with (staged / '.hq-extraction.log').open('w') as log:
            subprocess.run([str(extractor), '--extract', '--collisions=rename-all', '--color=0',
                            '--progress=0', '--output-dir', str(payload), str(installer / 'setup.exe')],
                           check=True, stdout=log, stderr=subprocess.STDOUT)
        if not (payload / 'app').is_dir():
            raise ValueError('HQ installer has no app payload')
        for name, options in (
                ('.hq-inventory.txt', ['--list', '--collisions=rename-all', '--list-checksums']),
                ('.hq-setup-metadata.txt', ['--debug', '--list'])):
            with (staged / name).open('w') as log:
                subprocess.run([str(extractor), *options, '--color=0', str(installer / 'setup.exe')],
                               check=True, stdout=log, stderr=subprocess.STDOUT)
        manifest = normalize_payload(payload / 'app', staged)
        manifest.update({'version': '1.20.9', 'archive_sha256': sha256(archive),
                         'inputs': inputs, 'extractor_sha256': sha256(extractor)})
        (staged / '.hq-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        staged.rename(destination)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--extractor', type=Path, default=Path('out/tools/hq-extractor/build/innoextract'))
    args = parser.parse_args()
    result = extract_hq(args.archive, args.destination, args.extractor)
    print(f'Extracted {len(result["files"])} HQ files; {len(result["variants"])} optional variants')
