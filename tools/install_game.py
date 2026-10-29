#!/usr/bin/env python3
"""Extract the supplied four-disc PC backup without running Windows programs."""
import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile

EXE_SHA = '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'
D3DX_SHA = '8ea96fe01c3c86a36fcb3795ae03eb12034003e335ef475571efaeda17c5bc78'


class RawISO(io.RawIOBase):
    """A bounded, seekable logical-byte view of a MODE1/2352 image."""
    def __init__(self, path, base=0, size=None):
        super().__init__()
        self.file = open(path, 'rb')
        self.file.seek(0, 2)
        total = self.file.tell()
        self.file.seek(0)
        header = self.file.read(16)
        if total % 2352 or header[:12] != b'\0' + b'\xff' * 10 + b'\0' or header[15:] != b'\x01':
            self.file.close()
            raise ValueError(f'{Path(path).name}: invalid MODE1/2352 image')
        logical = total // 2352 * 2048
        self.base = base
        self.size = logical - base if size is None else size
        self.pos = 0
        if base < 0 or self.size < 0 or base + self.size > logical:
            self.close()
            raise ValueError('file extent outside disc image')

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError('invalid seek mode')
        pos = offset + (0 if whence == 0 else self.pos if whence == 1 else self.size)
        if pos < 0:
            raise ValueError('negative seek')
        self.pos = pos
        return pos

    def read(self, n=-1):
        n = max(0, self.size - self.pos) if n < 0 else max(0, min(n, self.size - self.pos))
        if not n:
            return b''
        first, offset = divmod(self.base + self.pos, 2048)
        count = (offset + n + 2047) // 2048
        self.file.seek(first * 2352)
        raw = self.file.read(count * 2352)
        if len(raw) != count * 2352:
            raise ValueError('truncated disc sector')
        logical = b''.join(raw[i + 16:i + 2064] for i in range(0, len(raw), 2352))
        self.pos += n
        return logical[offset:offset + n]

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self.file.close()
        super().close()


@dataclass(frozen=True)
class DiscFile:
    name: str
    offset: int
    size: int


def disc_files(path):
    with RawISO(path) as image:
        root = None
        joliet = False
        for sector in range(16, 80):
            image.seek(sector * 2048)
            descriptor = image.read(2048)
            if len(descriptor) != 2048 or descriptor[1:6] != b'CD001':
                raise ValueError('invalid ISO volume descriptor')
            kind = descriptor[0]
            if kind == 255:
                break
            if kind == 1 and root is None:
                root = descriptor[156:190]
            if kind == 2 and descriptor[88:91] in (b'%/@', b'%/C', b'%/E'):
                root, joliet = descriptor[156:190], True
        if root is None:
            raise ValueError('missing ISO root directory')
        files = []
        visited = set()

        def walk(record, prefix='', depth=0):
            lba, size = struct.unpack_from('<I', record, 2)[0], struct.unpack_from('<I', record, 10)[0]
            if depth > 32 or (lba, size) in visited or size > 16 * 1024 * 1024:
                raise ValueError('invalid ISO directory tree')
            visited.add((lba, size))
            image.seek(lba * 2048)
            data = image.read(size)
            if len(data) != size:
                raise ValueError('ISO directory outside disc')
            at = 0
            while at < len(data):
                n = data[at]
                if not n:
                    at = (at // 2048 + 1) * 2048
                    continue
                record = data[at:at + n]
                at += n
                if n < 34 or len(record) != n or 33 + record[32] > n:
                    raise ValueError('invalid ISO directory record')
                raw_name = record[33:33 + record[32]]
                if raw_name in (b'\0', b'\1'):
                    continue
                name = raw_name.decode('utf-16-be' if joliet else 'ascii').split(';')[0]
                if '/' in name or '\\' in name or name in ('.', '..'):
                    raise ValueError('unsafe ISO filename')
                full = prefix + name
                if record[25] & 2:
                    walk(record, full + '/', depth + 1)
                else:
                    offset = struct.unpack_from('<I', record, 2)[0] * 2048
                    length = struct.unpack_from('<I', record, 10)[0]
                    if offset + length > image.size:
                        raise ValueError('ISO file outside disc')
                    files.append(DiscFile(full, offset, length))
        walk(root)
        return files


def extract_zip(archive, root):
    root = Path(root).resolve()
    count = 0
    for info in archive.infolist():
        name = info.filename.replace('\\', '/')
        parts = PurePosixPath(name).parts
        if not parts or name.startswith('/') or '..' in parts or ':' in name or '\0' in name:
            raise ValueError(f'unsafe ZIP path: {info.filename}')
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f'ZIP symlink refused: {info.filename}')
        target = root.joinpath(*parts)
        if not target.resolve().is_relative_to(root):
            raise ValueError(f'ZIP path escapes destination: {info.filename}')
        if name.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, target.open('wb') as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        count += 1
    return count


def verify_binary(data, expected):
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('unsupported binary SHA-256')
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('not a PE executable')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if data[offset:offset + 4] != b'PE\0\0' or data[offset + 4:offset + 6] != b'\x4c\x01':
        raise ValueError('expected an i386 PE, not x64')


def install(backup, destination):
    backup, destination = Path(backup), Path(destination)
    if destination.exists():
        raise FileExistsError('destination already exists; keeping it untouched')
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'archives': [], 'binaries': {'speed.exe': EXE_SHA, 'd3dx9_26.dll': D3DX_SHA}}
    with tempfile.TemporaryDirectory(prefix='.nfsmw-install-', dir=destination.parent) as work:
        staging = Path(work) / 'game'
        staging.mkdir()
        images = sorted(backup.glob('*.bin'))
        if len(images) != 4:
            raise ValueError('expected four PC disc images')
        found_d3dx = False
        for image in images:
            print(f'Reading {image.name}', flush=True)
            files = disc_files(image)
            archives = [f for f in files if f.name.lower().endswith('.zip') and 'compres' in f.name.lower()]
            if len(archives) != 1:
                raise ValueError('expected one game ZIP per disc')
            entry = archives[0]
            with RawISO(image, entry.offset, entry.size) as raw, io.BufferedReader(raw) as stream, zipfile.ZipFile(stream) as z:
                count = extract_zip(z, staging)
            manifest['archives'].append({'disc': image.name, 'archive': entry.name, 'files': count})
            print(f'  Extracted and CRC-checked {count} files', flush=True)
            for entry in files:
                low = entry.name.lower()
                if low in ('server.dll', 'server.cfg') or (low=='bin.dat' and image==images[0]):
                    with RawISO(image, entry.offset, entry.size) as raw:
                        (staging / low).write_bytes(raw.read())
                if not found_d3dx and low.startswith('directx/') and low.endswith('.cab') and 'jun' in low:
                    with RawISO(image, entry.offset, entry.size) as raw:
                        cab = Path(work) / 'directx.cab'
                        cab.write_bytes(raw.read())
                    result = subprocess.run(['cabextract', '-p', '-F', 'd3dx9_26.dll', str(cab)], capture_output=True)
                    if result.returncode == 0 and hashlib.sha256(result.stdout).hexdigest() == D3DX_SHA:
                        verify_binary(result.stdout, D3DX_SHA)
                        (staging / 'd3dx9_26.dll').write_bytes(result.stdout)
                        found_d3dx = True
        if not found_d3dx:
            raise ValueError('required x86 d3dx9_26.dll not found on supplied discs')
        updates = list(backup.glob('*.zip'))
        if len(updates) != 1:
            raise ValueError('expected the supplied v1.3 update ZIP')
        with zipfile.ZipFile(updates[0]) as z:
            names = [n for n in z.namelist() if n.lower().endswith('/speed.exe')]
            if len(names) != 1:
                raise ValueError('expected one speed.exe in the update ZIP')
            data = z.read(names[0])
            verify_binary(data, EXE_SHA)
            (staging / 'speed.exe').write_bytes(data)
        (staging / 'install-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        staging.rename(destination)
    print(f'Installed {sum(x["files"] for x in manifest["archives"])} archive files; both binary hashes verified.', flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    install(args.backup, args.destination)
