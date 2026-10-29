"""Decode the supplied official 1.3 full replacement records without executing its EXE."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

PATCH_EXE_SHA = '4c858e9b63ae2f856af7f1c090d5ce3d8c75246e9c0f7018ff57efb87addd0ef'
PATCH_EXE_SIZE = 12777356
# Known RTPatch 7.00 full replacement records; offsets are relative to K* at 0xc2400.
RECORDS = (
    ('FRONTEND/FrontB.lzc', 0xe0, 2901454, 2921499, 0x23c8bb62, 0x18f41549,
     'ec9c4934ecece45a4ad8da878785964de2449804f67e85dd755ae0c31bcab021'),
    ('GLOBAL/gameplay.bin', 0x2c4714, 619695, 2105216, 0x1ba1d4a9, 0x3d997b7b,
     '6eb317c578ab44176fa0bdd2d1b530bf4dfbae0f648980ee3af72212ae391314'),
    ('GLOBAL/gameplay.lzc', 0x35bc29, 716601, 779956, 0x7d2c898c, 0x08430c34,
     '33d5bb2631db6691d6651738c0f2746233dea673dc1f436e5973e741084d8559'),
    ('GLOBAL/InGameB.bun', 0x40abc6, 468246, 946264, 0x491fd26f, 0x0ad57773,
     '934bae4ee1a728af252d65dbabde896eac665103d152b60099b705f499fb0879'),
    ('GLOBAL/InGameB.lzc', 0x47d140, 519594, 522637, 0x21dd18c1, 0x12c68746,
     'a6ae7c8d1877ad114f1c3ac8f612aa64e5fabdf249bd478314ffb821dcc6354f'),
    ('server.dll', 0x4fbf41, 222908, 380928, 0x50393f85, 0x34f7562c,
     'c4fdd0e9e779be7f4be7728b03339eda4fd27248ceb9d2c640403b8fc90587ff'),
    ('speed.exe', 0x532652, 6532400, 7254894, 0x6552f2de, 0x0c3e8a3a,
     'e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb'),
)


def read_patch_payload(archive: Path) -> bytes:
    """Accept the pinned publisher EXE or its original single-member ZIP."""
    archive=Path(archive)
    if archive.is_symlink():raise ValueError('unsupported official patch symlink')
    with archive.open('rb') as stream:
        direct=stream.read(2)==b'MZ'
        if direct:
            stream.seek(0);data=stream.read(PATCH_EXE_SIZE+1)
    if not direct:
        try:
            with zipfile.ZipFile(archive) as zipped:
                members=zipped.infolist()
                if(len(members)!=1 or members[0].filename!='nfsmwpatch1.3.exe' or
                        members[0].file_size!=PATCH_EXE_SIZE):
                    raise ValueError('unsupported official patch archive')
                data=zipped.read(members[0])
        except zipfile.BadZipFile as error:
            raise ValueError('unsupported official patch archive')from error
    if len(data)!=PATCH_EXE_SIZE or hashlib.sha256(data).hexdigest()!=PATCH_EXE_SHA:
        raise ValueError('unsupported official patch executable hash')
    return data


def apply_official_patch(archive: Path, destination: Path) -> dict:
    """Verify and stage all seven replacements, then return {relative_path: {size, sha256}}.

    The destination must be an existing installer staging directory. Decoding and
    verification finish before any files there are replaced. Each replacement is
    atomic; the caller owns publishing the complete staged installation.
    """
    archive, destination = Path(archive), Path(destination)
    data=read_patch_payload(archive)
    if not destination.is_dir() or destination.is_symlink():
        raise ValueError('official patch destination must be an existing staging directory')
    for name, *_ in RECORDS:
        target = destination / name
        for path in (target, *target.parents):
            if path == destination:
                break
            if path.is_symlink() or (path.exists() and path != target and not path.is_dir()):
                raise ValueError(f'unsafe official patch destination: {name}')
        if target.is_dir():
            raise ValueError(f'official patch destination is a directory: {name}')
    rustc = shutil.which('rustc')
    if rustc is None:
        raise RuntimeError('rustc is required to decode the official patch natively')
    source = Path(__file__).with_name('rtpatch_decode.rs')
    with tempfile.TemporaryDirectory(prefix='.official-patch-', dir=destination.parent) as tmp:
        stage = Path(tmp)
        executable = stage / 'patch.exe'
        executable.write_bytes(data)
        decoder = stage / 'decode'
        subprocess.run([rustc, '--edition=2021', '-O', str(source), '-o', str(decoder)],
                       check=True, capture_output=True)
        manifest = {}
        for name, offset, size, expected, w1, w2, sha in RECORDS:
            output = stage / 'files' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(decoder), str(executable), str(0xc2400 + offset),
                            str(size), str(expected), str(w1), str(w2), str(output)],
                           check=True, capture_output=True)
            if hashlib.sha256(output.read_bytes()).hexdigest() != sha:
                raise ValueError(f'official patch decoded hash mismatch: {name}')
            manifest[name] = {'size': expected, 'sha256': sha}
        for name in manifest:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / 'files' / name, target)
    return manifest
