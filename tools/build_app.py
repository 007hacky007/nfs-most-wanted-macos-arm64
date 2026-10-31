#!/usr/bin/env python3
"""Build NFSMW.app from your extracted game folder or ISO / BIN/CUE discs."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
import progress  # noqa: E402

PATCH_KEYS = ('official-1.3', 'widescreen', 'mw-hq')
STEP_FAILED = 'This step stopped with an error. Click Copy log and include it in a bug report.'


class GameCopyError(ValueError):
    """The game copy check failed; carries the full report for the Builder."""
    def __init__(self, report):
        super().__init__(report['message'])
        self.report = report


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


def check_platform():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise ValueError('building requires macOS on Apple Silicon')
    if sys.version_info < (3, 12):
        raise ValueError('Python 3.12 or later is required')


def prerequisites(helpers=False):
    check_platform()
    # Prebuilt helpers replace cmake (innoextract) and rustc (the official patch decoder).
    names = ('clang', 'codesign') if helpers else ('clang', 'cmake', 'rustc', 'codesign')
    missing = [name for name in names if shutil.which(name) is None]
    if not Path('/usr/bin/tar').is_file():
        missing.append('/usr/bin/tar')
    if missing:
        raise ValueError('missing build tools: ' + ', '.join(missing) + '; see README.md')


def requirements_digest():
    return hashlib.sha256((ROOT / 'requirements.txt').read_bytes()).hexdigest()


def environment():
    """Create the project environment once, using the pinned build dependencies."""
    python = ROOT / '.venv/bin/python'
    stamp = ROOT / '.venv/.build-requirements-sha256'
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
    check = ('from importlib.metadata import version; '
             'assert version("capstone")=="5.0.9"; '
             'assert version("pefile")=="2024.8.26"')
    result = subprocess.run([str(python), '-c', check], capture_output=True)
    if result.returncode:
        progress.step('setup', 'Setting up Python build dependencies in .venv')
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                        '-r', str(ROOT / 'requirements.txt')], check=True)
    # NFSMW Builder compares this stamp with requirements.txt to know the packages are set up.
    stamp.write_text(requirements_digest())
    if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])


def cache_directory(value=None):
    """--cache-dir, else NFSMW_CACHE_DIR, else out/downloads in this checkout."""
    value = value or os.environ.get('NFSMW_CACHE_DIR')
    return Path(value).expanduser().resolve() if value else ROOT / 'out/downloads'


def fetch_all(keys, cache):
    """Fetch pinned downloads with one running byte count over all of them."""
    from patch_sources import SOURCES, fetch_patch
    total = sum(SOURCES[key].size for key in keys)
    done, paths = 0, {}
    for key in keys:
        paths[key] = fetch_patch(key, cache, progress=lambda got, _, key=key, base=done:
                                 progress.download(key, base + got, total))
        done += SOURCES[key].size
    return paths


def build(sources, cache=None, helper_dir=None):
    import fcntl
    from game_sources import check_sources
    from install_game import install
    from package_app import package_app
    from prepare_public_hq import prepare_build

    output = ROOT / 'out'
    output.mkdir(exist_ok=True)
    cache = cache_directory() if cache is None else Path(cache)
    with (output / 'app-build.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        progress.step('check', 'Checking your game copy')
        report = check_sources(sources)
        if not report['ok']:
            raise GameCopyError(report)
        print('Accepted ' + report['version'], flush=True)
        progress.step('downloads', 'Fetching and verifying the pinned patches (HQ download is 3.34 GB).')
        keys = PATCH_KEYS if helper_dir else (*PATCH_KEYS, 'hq-extractor')
        fetched = fetch_all(keys, cache)
        patches = {key: fetched[key] for key in PATCH_KEYS}
        # Fresh source prevents an edited extraction cache becoming a build input.
        with tempfile.TemporaryDirectory(prefix='app-build-', dir=output) as temporary:
            stage = Path(temporary)
            if helper_dir:
                from helpers import load
                progress.step('tools', 'Checking the bundled extraction tools')
                tools = load(helper_dir)
                extractor, decoder = tools['innoextract'], tools['rtpatch-decode']
            else:
                from build_hq_extractor import build_extractor
                progress.step('tools', 'Building the native HQ extractor')
                extractor, decoder = build_extractor(fetched['hq-extractor'], stage / 'extractor'), None
            game = stage / 'game'
            install(sources, game, patches=patches, extractor=extractor, decoder=decoder)
            preparation = output / ('app-preparation-' + str(time.time_ns()))
            prepare_build(game, preparation)
            progress.step('package', 'Packaging and signing NFSMW.app with your game files')
            app = package_app(output / 'nfsmw_boot', game, output / 'NFSMW.app')
        print('Built ' + str(app) + '\nOpen it to choose resolution and game mode.', flush=True)
        if progress.enabled():
            progress.emit({'done': str(app.resolve())})
        return app


def log_path(message):
    match = re.search(r'inspect (\S+)$', message)
    return match.group(1) if match else None


class Parser(argparse.ArgumentParser):
    def error(self, message):
        progress.error(message, log=None)
        super().error(message)


def main(argv=None):
    # Cancel sends SIGTERM to the process group: unwind so temporary folders are removed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    argv = sys.argv[1:] if argv is None else argv
    if '--progress' in argv:
        os.environ['NFSMW_PROGRESS'] = '1'
    parser = Parser(description=__doc__)
    parser.add_argument('source', nargs='*', help='extracted game folder, image folder, or all ISO / BIN/CUE discs')
    parser.add_argument('--progress', action='store_true', help='print NFSMW-EVENT JSON progress lines')
    parser.add_argument('--setup-only', action='store_true', help='only check the Mac and set up Python packages')
    parser.add_argument('--cache-dir', help='download cache (default NFSMW_CACHE_DIR, else out/downloads)')
    parser.add_argument('--helpers', type=Path, help='folder with prebuilt helpers and helpers.json')
    args = parser.parse_args(argv)
    try:
        if args.setup_only:
            check_platform()
            environment()
            print('Python build dependencies are ready.', flush=True)
            return 0
        if not args.source:
            parser.error('the following arguments are required: source')
        sources = resolve_sources(args.source)
        cache = cache_directory(args.cache_dir)
        helper_dir = args.helpers.expanduser().resolve() if args.helpers else None
        prerequisites(helpers=helper_dir is not None)
        environment()
        os.chdir(ROOT)
        build(sources, cache, helper_dir)
    except GameCopyError as error:
        print('Build failed: ' + str(error), file=sys.stderr, flush=True)
        progress.error(str(error), report=error.report)
        return 2
    except subprocess.CalledProcessError as error:
        print('Build failed: ' + str(error), file=sys.stderr, flush=True)
        progress.error(STEP_FAILED, log=None)
        return 2
    except (ValueError, OSError, RuntimeError) as error:
        print('Build failed: ' + str(error), file=sys.stderr, flush=True)
        progress.error(str(error), log=log_path(str(error)))
        return 2
    except KeyboardInterrupt:
        print('Build interrupted. The previous app is preserved.', file=sys.stderr, flush=True)
        return 130
    except Exception as error:  # noqa: BLE001 - the Builder must always get an error event
        print('Build failed: ' + repr(error), file=sys.stderr, flush=True)
        progress.error(STEP_FAILED, log=None)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
