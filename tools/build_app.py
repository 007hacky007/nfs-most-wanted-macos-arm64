#!/usr/bin/env python3
"""Build NFSMW.app from your extracted game folder or ISO / BIN/CUE discs."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def resolve_sources(arguments, directory=None):
    directory = Path.cwd() if directory is None else Path(directory)
    inputs = [directory / name for name in arguments]
    if any(path.is_symlink() for path in inputs):
        raise ValueError('source symlinks are not supported')
    sources = [path.resolve() for path in inputs]
    for path in sources:
        if not path.exists():
            raise ValueError('source does not exist: ' + str(path))
    return sources


def prerequisites():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise ValueError('building requires macOS on Apple Silicon')
    if sys.version_info < (3, 12):
        raise ValueError('Python 3.12 or later is required')
    missing = [name for name in ('clang', 'cmake', 'cabextract', 'rustc', 'codesign')
               if shutil.which(name) is None]
    if missing:
        raise ValueError('missing build tools: ' + ', '.join(missing) + '; see README.md')


def environment():
    """Create the project environment once, using the pinned build dependencies."""
    python = ROOT / '.venv/bin/python'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
    check = ('from importlib.metadata import version; '
             'assert version("capstone")=="5.0.9"; '
             'assert version("pefile")=="2024.8.26"')
    result = subprocess.run([str(python), '-c', check], capture_output=True)
    if result.returncode:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])


def build(sources):
    import fcntl
    from patch_sources import fetch_patch
    from build_hq_extractor import build_extractor
    from install_game import install
    from package_app import package_app
    from prepare_public_hq import prepare_build

    output = ROOT / 'out'
    output.mkdir(exist_ok=True)
    with (output / 'app-build.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        print('Fetching and verifying the pinned patches (HQ download is 3.34 GB).', flush=True)
        patches = {key: fetch_patch(key) for key in ('official-1.3', 'widescreen', 'mw-hq')}
        archive = fetch_patch('hq-extractor')
        # Fresh source prevents an edited extraction cache becoming a build input.
        with tempfile.TemporaryDirectory(prefix='app-build-', dir=output) as temporary:
            stage = Path(temporary)
            extractor = build_extractor(archive, stage / 'extractor')
            game = stage / 'game'
            install(sources, game, patches=patches, extractor=extractor)
            preparation=output/('app-preparation-'+str(time.time_ns()))
            prepare_build(game, preparation)
            app = package_app(output / 'nfsmw_boot', game)
        print('Built ' + str(app) + '\nOpen it to choose resolution and game mode.', flush=True)
        return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='+', help='extracted game folder, image folder, or all ISO / BIN/CUE discs')
    args = parser.parse_args()
    try:
        sources = resolve_sources(args.source)
        prerequisites()
        environment()
        os.chdir(ROOT)
        build(sources)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(2, 'Build failed: ' + str(error) + '\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Build interrupted. The previous app is preserved.\n')


if __name__ == '__main__':
    main()
