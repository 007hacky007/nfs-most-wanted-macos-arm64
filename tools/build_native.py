#!/usr/bin/env python3
"""Compile generated ARM64 modules and the native runtime, with content caching."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import fcntl
import os
from pathlib import Path
import subprocess
import sys

FLAGS = ['-O2', '-mcpu=apple-m1', '-mmacosx-version-min=11.0', '-fno-strict-aliasing',
         '-Wno-unused-label', '-Wno-parentheses-equality', '-Iruntime', '-Igen/all', '-DNFS_ENHANCED=0']
CSRC = 'mem dispatch heap watchdog win32 win32_ext win_keyboard msvcrt com res fileio vsemu enhance perflog lifecycle dinput_pad dikeys keyboard dinput_kbd winsock net_vlan net_relay online module modheap texpack automation mw_platform main'.split()
MSRC = 'app metal audio net_native gamepad keyboard_mac fpscounter texrep'.split()
FRAMEWORKS = 'Cocoa Metal QuartzCore ImageIO CoreGraphics CoreServices AudioToolbox CoreAudio GameController Carbon AVFoundation'.split()


def compile_file(item):
    source, folder = item
    folder.mkdir(parents=True, exist_ok=True)
    obj = folder / (source.stem + '.o')
    flags = FLAGS + (['-fobjc-arc'] if source.suffix == '.m' else [])
    if source == Path('gen/d3dx/shard_0047.c'):
        # shortcut: split this large D3DX CFG before enabling Apple Clang O2 here.
        flags = ['-O0' if f == '-O2' else f for f in flags]
    digest = hashlib.sha256(source.read_bytes() + HEADERS + str(flags).encode()).hexdigest()
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
    Path('out').mkdir(exist_ok=True)
    build_lock = open('out/build.lock', 'w')
    fcntl.flock(build_lock, fcntl.LOCK_EX)
    subprocess.run([sys.executable,'tools/lift_callbacks.py'],check=True)
    HEADERS = b''.join(p.read_bytes() for p in sorted(Path('runtime').glob('*.h')))
    HEADERS += b''.join(p.read_bytes() for p in Path('gen').glob('*/decls.h'))
    files = []
    for module in ('all', 'd3dx', 'dynamic'):
        for p in sorted((Path('gen') / module).glob('*.c')):
            files.append((p, Path('out/obj') / module))
    if not files:
        sys.exit('run ./gen.sh first')
    if '--shards' not in sys.argv:
        files += [(Path('runtime') / (n + '.c'), Path('out/obj/runtime')) for n in CSRC]
        files += [(Path('runtime') / (n + '.m'), Path('out/obj/runtime')) for n in MSRC]
    try:
        with ThreadPoolExecutor(max_workers=int(os.environ.get('J', '8'))) as pool:
            objects = list(pool.map(compile_file, files))
        if '--shards' not in sys.argv:
            cmd = ['clang', '-mmacosx-version-min=11.0', '-Wl,-dead_strip', '-o', 'out/nfsmw_boot', *map(str, objects), '-lm', '-lz']
            for framework in FRAMEWORKS:
                cmd += ['-framework', framework]
            subprocess.run(cmd, check=True)
            print('Linked out/nfsmw_boot')
    except (RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error) if isinstance(error, RuntimeError) else f'Link failed: {error.returncode}')
