#!/usr/bin/env python3
"""Build and assemble NFSMW Builder.app (ad-hoc signed).

--helpers names the tools/build_helpers.py output (innoextract and the RTPatch decoder);
every app needs it. The Builder runs the pipeline with PATH=/usr/bin:/bin:/usr/sbin:/sbin,
so an app without helpers could not find cmake or rustc and could never build. For quick
UI work without helpers, use `swift run --package-path builder NFSMWBuilder` instead.
"""
import argparse
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import helpers as helper_tools  # noqa: E402

ENTRIES = ('build.sh', 'gen.sh', 'requirements.txt', 'LICENSE', 'tools', 'runtime', 'third_party')
MIN_MACOS = '12.0'
BUNDLE_ID = 'local.nfsmw.builder'
# Game files, patch archives and disc images never go into the bundle.
FORBIDDEN_SUFFIXES = ('.exe', '.dll', '.asi', '.bun', '.lzc', '.big', '.zip', '.iso', '.bin', '.cue', '.cab')
MAX_FILE_BYTES = 2 * 1024 * 1024
VERSION = re.compile(r'\d+\.\d+\.\d+')


def build_sources(root):
    """Tracked files the Builder bundles, relative to the repo root."""
    out = subprocess.run(['git', 'ls-files', '-z', '--', *ENTRIES], cwd=root, check=True,
                         capture_output=True).stdout.decode()
    return sorted(Path(n) for n in out.split('\0') if n and '__pycache__' not in Path(n).parts)


def check_bundle(paths, root):
    """Refuse game or archive files and anything unexpectedly large."""
    for relative in paths:
        if relative.suffix.casefold() in FORBIDDEN_SUFFIXES:
            raise ValueError(f'refusing to bundle {relative}: game or archive file type')
        source = Path(root) / relative
        if not source.is_file():
            raise ValueError(f'tracked file is missing from the checkout: {relative}')
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f'refusing to bundle {relative}: larger than 2 MB')


def parse_minos(otool_output):
    if 'LC_BUILD_VERSION' not in otool_output:
        raise ValueError('no LC_BUILD_VERSION load command')
    block = otool_output.split('LC_BUILD_VERSION', 1)[1]
    match = re.search(r'minos (\S+)', block)
    if not match:
        raise ValueError('no minos in LC_BUILD_VERSION')
    return match.group(1)


def build_binary(root, scratch=None):
    command = ['swift', 'build', '--package-path', str(root / 'builder'), '-c', 'release', '--arch', 'arm64']
    if scratch:
        command += ['--scratch-path', str(scratch)]
    subprocess.run(command, check=True)
    shown = subprocess.run(command + ['--show-bin-path'], check=True, capture_output=True, text=True).stdout.strip()
    binary = Path(shown) / 'NFSMWBuilder'
    minos = parse_minos(subprocess.run(['otool', '-l', str(binary)], check=True, capture_output=True,
                                       text=True).stdout)
    if minos != MIN_MACOS:
        raise SystemExit(f'{binary} targets macOS {minos}, expected {MIN_MACOS}')
    print(f'minos {minos}')
    return binary


def make_icns(png, destination):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / 'AppIcon.iconset'
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f'icon_{size}x{size}{"@2x" if scale == 2 else ""}.png'
                subprocess.run(['sips', '-z', str(size * scale), str(size * scale), str(png), '--out',
                                str(iconset / name)], check=True, capture_output=True)
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(destination)], check=True)


def info_plist(version):
    return {
        'CFBundleIdentifier': BUNDLE_ID, 'CFBundleName': 'NFSMW Builder', 'CFBundleDisplayName': 'NFSMW Builder',
        'CFBundleExecutable': 'NFSMWBuilder', 'CFBundlePackageType': 'APPL', 'CFBundleInfoDictionaryVersion': '6.0',
        'CFBundleShortVersionString': version, 'CFBundleVersion': version, 'LSMinimumSystemVersion': MIN_MACOS,
        'NSHighResolutionCapable': True, 'NSPrincipalClass': 'NSApplication', 'CFBundleIconFile': 'AppIcon',
    }


def assemble(binary, version, output, root, helper_dir):
    sources = build_sources(root)
    check_bundle(sources, root)
    helper_tools.load(helper_dir, root)
    app = Path(output) / 'NFSMW Builder.app'
    if app.exists():
        shutil.rmtree(app)
    macos, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.copy2(binary, macos / 'NFSMWBuilder')
    bundled = resources / 'BuildSources'
    for rel in sources:
        target = bundled / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)
    (bundled / 'helpers').mkdir()
    for name in (*helper_tools.NAMES, 'helpers.json'):
        shutil.copy2(Path(helper_dir) / name, bundled / 'helpers' / name)
    helper_tools.load(bundled / 'helpers', root)
    make_icns(root / 'builder/Resources/AppIcon-1024.png', resources / 'AppIcon.icns')
    with open(app / 'Contents/Info.plist', 'wb') as f:
        plistlib.dump(info_plist(version), f)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', default='dist')
    parser.add_argument('--helpers', type=Path, required=True,
                        help='tools/build_helpers.py output folder (innoextract, rtpatch-decode, helpers.json)')
    parser.add_argument('--scratch-path', type=Path, help='SwiftPM build folder (default builder/.build)')
    args = parser.parse_args(argv)
    if not VERSION.fullmatch(args.version):
        parser.error('--version must look like 1.2.3 (from a v1.2.3 tag)')
    try:
        app = assemble(build_binary(ROOT, args.scratch_path), args.version, Path(args.output), ROOT, args.helpers)
    except ValueError as error:
        parser.exit(1, f'make_builder: {error}\n')
    print(app)
    return 0


if __name__ == '__main__':
    sys.exit(main())
