#!/usr/bin/env python3
"""Machine-readable helpers for NFSMW Builder. Prints NFSMW-EVENT JSON lines.

Runs from the workspace .venv Python. Every failure, expected or not, ends with one
{"error": ...} event and a nonzero exit status. check-game never writes anywhere.
"""
import argparse
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))
import build_app  # noqa: E402
import game_sources  # noqa: E402
import patch_sources  # noqa: E402
from progress import emit  # noqa: E402

NOT_HQ = 'This is not MW_HQ_1.20.9.zip: its size or checksum is different.'
SMALL_BYTES = patch_sources.RESUMABLE_BYTES


def needed(helpers):
    return build_app.PATCH_KEYS if helpers else (*build_app.PATCH_KEYS, 'hq-extractor')


def status(key, cache):
    """ready, partial or missing. Large files are only size-checked here; the build verifies them."""
    spec = patch_sources.SOURCES[key]
    path = cache / spec.filename
    if path.is_file() and not path.is_symlink() and path.stat().st_size == spec.size:
        if spec.size >= SMALL_BYTES:
            return 'ready'
        try:
            patch_sources.verify_patch(key, path)
            return 'ready'
        except ValueError:
            pass
    return 'partial' if patch_sources.partial_bytes(key, cache) else 'missing'


def run(args):
    if args.command == 'check-game':
        report = game_sources.check_sources([Path(p).expanduser() for p in args.paths])
        if not report['ok']:
            emit({'error': report['message'], 'report': report})
            return 1
        emit({'game': 'ok', 'version': report['version'], 'kind': report['kind']})
        return 0
    if args.command == 'accepted-copies':
        emit({'accepted': game_sources.accepted_copies()})
        return 0
    cache = build_app.cache_directory(args.cache_dir)
    if args.action == 'status':
        keys = needed(args.helpers)
        states = {key: status(key, cache) for key in keys}
        partial = {key: patch_sources.partial_bytes(key, cache) for key in keys if states[key] == 'partial'}
        sizes = {key: patch_sources.SOURCES[key].size for key in keys}
        remaining = sum(sizes[key] - partial.get(key, 0) for key in keys if states[key] != 'ready')
        emit({'downloads': states, 'partial_bytes': partial, 'total_bytes': sum(sizes.values()),
              'remaining_bytes': remaining})
    elif args.action == 'fetch':
        build_app.fetch_all(needed(args.helpers), cache)
        emit({'downloads': 'ready'})
    else:
        chosen = Path(args.path).expanduser()
        # Folders such as /tmp are symlinks; only the chosen file itself must not be one.
        chosen = chosen.parent.resolve() / chosen.name
        try:
            patch_sources.import_patch(args.key, chosen, cache)
        except ValueError:
            raise ValueError(NOT_HQ) from None
        emit({'downloads': 'ready'})
    return 0


def main(argv=None):
    # Cancel sends SIGTERM to the process group: unwind so temporary files are removed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check-game', help='check a game folder, an image folder or the four images'
                        ).add_argument('paths', nargs='+')
    commands.add_parser('accepted-copies', help='the accepted game copies, sizes and checksums')
    downloads = commands.add_parser('downloads', help='inspect, fetch or import the pinned downloads')
    actions = downloads.add_subparsers(dest='action', required=True)
    for name in ('status', 'fetch', 'import'):
        action = actions.add_parser(name)
        action.add_argument('--cache-dir', help='download cache (default NFSMW_CACHE_DIR, else out/downloads)')
        if name == 'import':
            action.add_argument('key', choices=('mw-hq',))
            action.add_argument('path')
        else:
            action.add_argument('--helpers', action='store_true', help='helpers are bundled; no innoextract source')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit:
        if exit.code:
            emit({'error': 'invalid builder command'})
        raise
    try:
        return run(args)
    except Exception as error:  # noqa: BLE001 - the Builder must always get an error event
        message = str(error) if isinstance(error, (ValueError, OSError, RuntimeError)) else build_app.STEP_FAILED
        print(repr(error), file=sys.stderr, flush=True)
        emit({'error': message})
        return 1


if __name__ == '__main__':
    sys.exit(main())
