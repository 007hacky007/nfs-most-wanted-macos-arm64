#!/usr/bin/env python3
"""Compile generated ARM64 modules and the native runtime, with content caching."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

FLAGS = ['-O2', '-mcpu=apple-m1', '-mmacosx-version-min=11.0', '-fno-strict-aliasing',
         '-Wno-unused-label', '-Wno-parentheses-equality', '-Iruntime', '-Igen/all', '-DNFS_ENHANCED=0']
CSRC = 'mem dispatch heap watchdog win32 win32_ext win_keyboard msvcrt com res fileio vsemu enhance perflog lifecycle dinput_pad dikeys keyboard dinput_kbd winsock net_vlan net_relay online module modheap texpack automation mw_platform mw_widescreen mw_unlimiter mw_texwizard mw_hdcontent mw_hdscaling mw_motionblur mw_fixes mw_fe_shadows mw_hud_adapter mw_hdreflections main'.split()
MSRC = 'app launcher metal audio net_native gamepad keyboard_mac fpscounter texrep'.split()
FRAMEWORKS = 'Cocoa Metal QuartzCore ImageIO CoreGraphics CoreServices AudioToolbox CoreAudio GameController Carbon AVFoundation'.split()
HQ_CSRC = 'hq_audio hq_capture hq_config hq_crt hq_image hq_import hq_kernel hq_native hq_plugin hq_prepare hq_route hq_sync hq_tls hq_video hq_xenon_math'.split()


def install_audio_callbacks(prepared, runtime, table, target):
    try:
        from . import prepare_audio_callbacks as audio
        from .runtime_image import STANDARD_RUNTIME_SHA256
    except ImportError:
        import prepare_audio_callbacks as audio
        from runtime_image import STANDARD_RUNTIME_SHA256
    prepared,runtime,table,target=map(Path,(prepared,runtime,table,target))
    state=audio._output_state(prepared)
    if state is None:
        raise ValueError('prepared audio callbacks are missing')
    record=json.loads((prepared/'manifest.json').read_text())
    runtime_hash=hashlib.sha256(runtime.read_bytes()).hexdigest()
    if (record.get('version')!=1 or record.get('source')!='callbacks.c' or
            runtime_hash!=STANDARD_RUNTIME_SHA256 or record.get('runtime_sha256')!=runtime_hash or
            record.get('native_table_sha256')!=hashlib.sha256(table.read_bytes()).hexdigest() or
            record.get('processors')!=audio._processors() or
            record.get('generation_profile')!=dict(audio.GENERATION_PROFILE)):
        raise ValueError('prepared audio provenance differs; prepare audio callbacks again')
    code=(prepared/'callbacks.c').read_bytes()
    if hashlib.sha256(code).hexdigest()!=record['files']['callbacks.c']:
        raise ValueError('prepared callback source checksum differs')
    if audio._output_state(prepared)!=state:
        raise ValueError('prepared audio changed during validation')
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('callback destination cannot be a symlink')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:
        staged=Path(stream.name)
        try:
            stream.write(code);stream.flush()
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)


def generated_sources(hq=False, routes=Path('out/hq-routes'), root=Path('.')):
    objects = root / ('out/obj-hq' if hq else 'out/obj')
    if not (root / 'gen/all/fntab.c').is_file():
        raise ValueError('run ./gen.sh first')
    replaced = set()
    if hq:
        record = json.loads((routes / 'manifest.json').read_text())
        replaced = set(record['replaced_shards'])
        if any(Path(name).name != name or not name.startswith('shard_') or
               not name.endswith('.c') for name in replaced):
            raise ValueError('invalid replacement shard name')
        if any(not (root / 'gen/all' / name).is_file() for name in replaced):
            raise ValueError('replacement shard is absent from the baseline')
    files = []
    for module in (('all', 'dynamic') if hq else ('all', 'd3dx', 'dynamic')):
        for source in sorted((root / 'gen' / module).glob('*.c')):
            if module == 'all' and source.name in replaced:
                source = routes / source.name
            files.append((source, objects / module))
    if hq:
        module_root = root / 'gen/hq-runtime'
        record = json.loads((module_root / '.hq-runtime.json').read_text())
        sources = record['sources']
        if len(sources) != len(set(sources)):
            raise ValueError('duplicate module source')
        for name in sources:
            path = Path(name)
            if path.is_absolute() or len(path.parts) != 2 or '..' in path.parts or path.suffix != '.c':
                raise ValueError('invalid module source')
            files.append((module_root / path, objects / 'modules' / path.parent))
        for name in ('variants', 'routes', 'register', 'native_names', 'checkpoints'):
            files.append((routes / (name + '.c'), objects / 'routes'))
    if not files:
        raise ValueError('run ./gen.sh first')
    missing = [str(source) for source, _ in files if not source.is_file()]
    if missing:
        raise ValueError('missing generated source: ' + ', '.join(missing))
    return files


def header_inputs(root=Path('.'), hq=False, routes=Path('out/hq-routes')):
    headers = set((root / 'runtime').glob('*.h')) | set((root / 'runtime').glob('*.inc'))
    headers.update((root / 'gen').glob('*/decls.h'))
    if hq:
        for suffix in ('*.h', '*.inc'):
            headers.update((root / 'gen/hq-runtime').rglob(suffix))
            headers.update(routes.glob(suffix))
    return b''.join(str(path).encode() + b'\0' + path.read_bytes() for path in sorted(headers))


def compile_file(item):
    source, folder = item
    folder.mkdir(parents=True, exist_ok=True)
    obj = folder / (source.stem + '.o')
    flags = FLAGS + (['-fobjc-arc'] if source.suffix == '.m' else [])
    data = source.read_bytes()
    if source.parent.name == 'd3dx' and b'void sub_0207c7cb(' in data:
        # shortcut: split this large D3DX CFG before enabling Apple Clang O2 here.
        flags = ['-O0' if f == '-O2' else f for f in flags]
    digest = hashlib.sha256(data + HEADERS + str(flags).encode()).hexdigest()
    stamp = obj.with_suffix('.sum')
    if obj.exists() and stamp.exists() and stamp.read_text() == digest:
        return obj
    result = subprocess.run(['clang', *flags, '-c', str(source), '-o', str(obj)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{source}:\n{result.stderr[-6000:]}')
    stamp.write_text(digest)
    print(f'Compiled {source}', flush=True)
    return obj


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shards', action='store_true', help='compile generated sources only')
    parser.add_argument('--hq', action='store_true', help='include the prepared Full HQ modules')
    parser.add_argument('--hq-routes', type=Path, default=Path('out/hq-routes'))
    parser.add_argument('--audio-callbacks', type=Path, help='verified offline callback preparation')
    args = parser.parse_args()
    Path('out').mkdir(exist_ok=True)
    build_lock = open('out/build.lock', 'w')
    fcntl.flock(build_lock, fcntl.LOCK_EX)
    try:
        if args.audio_callbacks:
            install_audio_callbacks(args.audio_callbacks,Path('out/target-image.txt').read_text().strip(),
                                    Path('gen/all/fntab.c'),Path('gen/dynamic/callbacks.c'))
        else:
            subprocess.run([sys.executable,'tools/lift_callbacks.py'],check=True)
        if args.hq:
            FLAGS += ['-DNFS_HQ_MODULES=1', '-Igen/hq-runtime', '-I' + str(args.hq_routes)]
            from prepare_hq_runtime import verify_runtime
            from prepare_hq_routes import verify_routes
            from prepare_hq_checkpoints import prepare as prepare_checkpoints
            verify_runtime()
            verify_routes(args.hq_routes, Path('gen/all'), Path('out/widescreen-hooks.txt'), Path('out/native-branches.txt'))
            prepare_checkpoints(args.hq_routes, args.hq_routes / 'checkpoints.c')
        HEADERS = header_inputs(hq=args.hq, routes=args.hq_routes)
        files = generated_sources(hq=args.hq, routes=args.hq_routes)
        if not args.shards:
            objects = Path('out/obj-hq/runtime' if args.hq else 'out/obj/runtime')
            files += [(Path('runtime') / (n + '.c'), objects) for n in CSRC + (HQ_CSRC if args.hq else [])]
            files += [(Path('runtime') / (n + '.m'), objects) for n in MSRC]
        with ThreadPoolExecutor(max_workers=int(os.environ.get('J', '8'))) as pool:
            objects = list(pool.map(compile_file, files))
        if not args.shards:
            cmd = ['clang', '-mmacosx-version-min=11.0', '-Wl,-dead_strip', '-o', 'out/nfsmw_boot', *map(str, objects), '-lm', '-lz']
            for framework in FRAMEWORKS:
                cmd += ['-framework', framework]
            subprocess.run(cmd, check=True)
            print('Linked out/nfsmw_boot')
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f'Link failed: {error.returncode}' if isinstance(error, subprocess.CalledProcessError) else str(error))
