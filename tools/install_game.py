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
HQ_EXE_SHA = '8393f3487e3e024d6c2196d8adcd3f5b1b38077a893d9161a6f9ac61d587fa19'
OFFICIAL_EXE_SHA = 'e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb'


class RawISO(io.RawIOBase):
    """A bounded logical-byte view of an ISO or a legacy MODE1/2352 image."""
    def __init__(self, path, base=0, size=None):
        super().__init__()
        self.file = open(path, 'rb')
        self.file.seek(0, 2)
        total = self.file.tell()
        self.file.seek(0)
        header = self.file.read(16)
        self.raw = header[:12] == b'\0' + b'\xff' * 10 + b'\0'
        if self.raw:
            valid = total % 2352 == 0 and header[15:] == b'\x01'
        else:
            self.file.seek(16 * 2048)
            valid = total % 2048 == 0 and self.file.read(7) == b'\x01CD001\x01'
        if not valid:
            self.file.close()
            raise ValueError(f'{Path(path).name}: invalid ISO or MODE1/2352 image')
        logical = total // 2352 * 2048 if self.raw else total
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
        if not self.raw:
            self.file.seek(self.base + self.pos)
            data = self.file.read(n)
            if len(data) != n:
                raise ValueError('truncated disc image')
            self.pos += n
            return data
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


def extract_cab_member(cabinet, member):
    """Read one member of a Microsoft cabinet with the system tar (libarchive), part of macOS."""
    result=subprocess.run(['/usr/bin/tar','-xOf',str(cabinet),member],capture_output=True)
    if result.returncode or not result.stdout:
        raise ValueError('could not decode the D3DX cabinet')
    return result.stdout


def supply_d3dx(archive, destination):
    """Decode the pinned HQ redistributable cabinet when a folder lacks D3DX."""
    member='Redist/dx/Jun2005_d3dx9_26_x86.cab'
    with zipfile.ZipFile(archive) as zipped:
        info=zipped.getinfo(member)
        if info.file_size!=1064925:raise ValueError('unsupported D3DX cabinet size')
        cabinet=zipped.read(info)
    if hashlib.sha256(cabinet).hexdigest()!='b448d7ba5b6fe1dc27639d42eb6ba0a997a793135678c729ba6756cfe4efc38b':
        raise ValueError('unsupported D3DX cabinet checksum')
    with tempfile.TemporaryDirectory(prefix='.nfsmw-d3dx-',dir=Path(destination).parent) as temporary:
        cab=Path(temporary)/'directx.cab';cab.write_bytes(cabinet)
        data=extract_cab_member(cab,'d3dx9_26.dll')
        verify_binary(data,D3DX_SHA)
        (Path(destination)/'d3dx9_26.dll').write_bytes(data)


def install(backup, destination, *, patches=None, hq_source=None,
            extractor=Path('out/tools/hq-extractor/build/innoextract'), decoder=None):
    """Stage a verified folder or disc set, apply patches, and publish once complete."""
    destination=Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('destination already exists; keeping it untouched')
    sources=[Path(backup)] if isinstance(backup,(str,Path)) else [Path(p) for p in backup]
    if not sources:raise ValueError('supply a game folder or all four disc images')
    if patches is None:
        folder=(sources[0] if sources[0].is_dir() else sources[0].parent)/'patches'
        official=folder/'nfsmwpatch1.3.exe'
        patches={'official-1.3':official if official.is_file() else folder/'nfsmwpatch1.3.zip',
                 'widescreen':folder/'NFSMostWanted.WidescreenFix.zip',
                 'mw-hq':folder/'MW_HQ_1.20.9.zip'}
    if set(patches)!={'official-1.3','widescreen','mw-hq'}:
        raise ValueError('provide official-1.3, widescreen and mw-hq patch paths')
    try:
        from .game_sources import stage_game
        from .official_patch import apply_official_patch
        from .patch_sources import verify_patch
        from .extract_hq import extract_hq
        from .hq_variants import build_variants
        from . import progress
    except ImportError:
        from game_sources import stage_game
        from official_patch import apply_official_patch
        from patch_sources import verify_patch
        from extract_hq import extract_hq
        from hq_variants import build_variants
        import progress
    verify_patch('widescreen',patches['widescreen'])
    verify_patch('mw-hq',patches['mw-hq'])
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nfsmw-install-',dir=destination.parent) as temporary:
        staging=Path(temporary)/'game';staging.mkdir()
        progress.step('game','Copying and checking all game files')
        source=stage_game(sources,staging)
        progress.step('patches','Applying the official 1.3 patch, D3DX and WidescreenFix')
        if not (staging/'d3dx9_26.dll').is_file():supply_d3dx(patches['mw-hq'],staging)
        verify_binary((staging/'d3dx9_26.dll').read_bytes(),D3DX_SHA)
        official=apply_official_patch(patches['official-1.3'],staging,decoder)
        verify_binary((staging/'speed.exe').read_bytes(),OFFICIAL_EXE_SHA)
        with zipfile.ZipFile(patches['widescreen']) as zipped:
            extract_zip(zipped,staging/'.nfsmw/windows/widescreen')
            for name in ('scripts/NFSMostWanted.WidescreenFix.ini','scripts/NFSMostWanted.WidescreenFix.tpk'):
                output=staging/name;output.parent.mkdir(parents=True,exist_ok=True)
                output.write_bytes(zipped.read(name))
        hq=Path(hq_source) if hq_source else Path(temporary)/'hq-source'
        if hq_source is None:
            progress.step('hq','Extracting verified HQ assets with the native installer reader')
            extract_hq(patches['mw-hq'],hq,extractor)
        progress.step('variants','Preparing isolated Standard, HQ visual and Full HQ data')
        variants=build_variants(staging,hq)
        manifest={'source':source,'archives':source['archives'],
                  'binaries':{'speed.exe':OFFICIAL_EXE_SHA,'d3dx9_26.dll':D3DX_SHA,
                              '.nfsmw/runtime.exe':EXE_SHA},
                  'patches':{'official-1.3':official,
                             'widescreen':{'implementation':'native'},
                             'mw-hq':{'version':variants['version'],'implementation':'native'}},
                  'variants':variants['variants']}
        (staging/'install-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        staging.rename(destination)
    print('Installed verified game files and patches.',flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--hq-source', type=Path, help='reuse an extracted and verified HQ source tree')
    parser.add_argument('--extractor', type=Path, default=Path('out/tools/hq-extractor/build/innoextract'))
    args = parser.parse_args()
    install(args.backup, args.destination, hq_source=args.hq_source, extractor=args.extractor)
