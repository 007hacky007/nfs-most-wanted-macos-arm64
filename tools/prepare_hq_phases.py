"""Prepare bounded code-write phases from verified, locally lifted module bodies."""
from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import pefile

try:
    from .generation_manifest import tool_hashes, options
    from .hq_module_catalog import MODULES, case_path, verify_inputs
    from .lift import Lifter
except ImportError:
    from generation_manifest import tool_hashes, options
    from hq_module_catalog import MODULES, case_path, verify_inputs
    from lift import Lifter

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.hq-phases.json'
GAME_SHA = '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'
GAME_BASE, GAME_SIZE = 0x400000, 0x678e4e
MODULE = next(module for module in MODULES if module.key == 'x360')
STOP_SITES = (0x01007b72, 0x0101394f)
FUNCTIONS = (0x01007b30, 0x01013660, 0x010010b0, 0x01001250, 0x010018d0,
             0x01001130, 0x01001300, 0x010069db, 0x01006a2c, 0x010015e0, 0x01006a7e)
MODELED = {0x01006a93, 0x01006af3, 0x01009780, 0x01010220, 0x01016f30}
CALLBACK_RANGES = ((0x005a30b1, 5),)
RENDER_RANGES = ((0x006de9f8, 8), (0x00642eaf, 5), (0x006c6d09, 5),
                 (0x006c6e12, 5), (0x006d770b, 5), (0x006e0486, 5), (0x006e5186, 5))
BRANCHES = ((0x00642eaf, 0xe9, 0x00642eda), (0x006c6d09, 0xe9, 0x0100c720),
            (0x006c6e12, 0xe8, 0x0100c7d0), (0x006d770b, 0xe8, 0x0100c0a0),
            (0x006e0486, 0xe8, 0x0100c0a0), (0x006e5186, 0xe8, 0x0100bdb0))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _no_symlinks(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if not part.is_symlink():
            continue
        # macOS exposes its root-owned temporary directories through these aliases.
        system_alias = (part != path and sys.platform == 'darwin' and str(part) in ('/var', '/tmp') and
                        part.lstat().st_uid == 0 and part.resolve() == Path('/private') / part.name)
        if not system_alias:
            raise ValueError('phase inputs and outputs must not use symlinks')
    return path.resolve()


def _output(path):
    path = _no_symlinks(path)
    if path.is_relative_to(ROOT) and (not path.relative_to(ROOT).parts or path.relative_to(ROOT).parts[0] not in ('out', 'gen')):
        raise ValueError('generated phase code must remain under ignored out/ or gen/')
    if path.exists():
        marker = path / MARKER
        if not path.is_dir() or marker.is_symlink() or not marker.is_file():
            raise ValueError('refusing to replace unmanaged phase output')
        try:
            record = json.loads(marker.read_text())
        except (ValueError, OSError) as error:
            raise ValueError('invalid managed phase output') from error
        if record.get('producer') != 'hq-phases' or record.get('version') != 1:
            raise ValueError('refusing to replace unmanaged phase output')
        if any(item.is_symlink() for item in path.rglob('*')):
            raise ValueError('managed phase output contains a symlink')
    return path


def _processors():
    result = tool_hashes()
    for name in ('tools/prepare_hq_phases.py', 'tools/hq_phase_driver.c', 'tools/hq_module_catalog.py',
                 'runtime/hq_config.c', 'runtime/hq_config.h', 'runtime/hq_config_fields.h', 'runtime/hq_xenon_fields.h'):
        result[name] = _sha((ROOT / name).read_bytes())
    return result


def _inputs(game_root, baseline, digest):
    game_root, baseline = _no_symlinks(game_root), _no_symlinks(baseline)
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('a verified upstream baseline SHA-256 is required')
    if not baseline.is_file() or baseline.stat().st_size != GAME_SIZE:
        raise ValueError('baseline must be a complete supported mapped game image')
    memory = baseline.read_bytes()
    if _sha(memory) != digest:
        raise ValueError('upstream baseline checksum differs')
    canonical = case_path(game_root, '.nfsmw/runtime.exe')
    if not canonical.is_file():
        canonical = case_path(game_root, 'speed.exe')
    if not canonical.is_file() or _sha(canonical.read_bytes()) != GAME_SHA:
        raise ValueError('canonical game executable checksum differs')
    game = pefile.PE(str(canonical))
    if game.OPTIONAL_HEADER.ImageBase != GAME_BASE or game.OPTIONAL_HEADER.SizeOfImage != GAME_SIZE:
        raise ValueError('unsupported mapped game identity')
    headers = game.OPTIONAL_HEADER.SizeOfHeaders
    if memory[:headers] != game.get_memory_mapped_image()[:headers]:
        raise ValueError('baseline PE headers differ from the canonical game')
    module = verify_inputs(game_root, [MODULE])[0]
    full = case_path(game_root, '.nfsmw/full')
    config = case_path(full if full.is_dir() else game_root, 'scripts/X360Stuff.ini')
    if not config.is_file():
        raise ValueError('selected X360 configuration is absent')
    return {'baseline': baseline, 'canonical': canonical, 'module': module, 'config': config}


def _generate(module, staged):
    image = pefile.PE(str(module))
    image.relocate_image(MODULE.base)
    relocated = staged / 'module.dll'
    image.write(str(relocated))
    memory = image.get_memory_mapped_image()[:MODULE.image_size]
    memory += bytes(MODULE.image_size - len(memory))
    (staged / 'module.memory.bin').write_bytes(memory)
    lifter = Lifter(str(relocated), hooks=STOP_SITES, trap=True, x87pc=True)
    bodies, references = [], set()
    for address in FUNCTIONS:
        code, calls = lifter.lift(address)
        bodies.append(code)
        references.update(calls)
    if lifter.traps or lifter.truncated:
        raise ValueError('original phase helper has unsupported or truncated instructions')
    if references - set(FUNCTIONS) != MODELED:
        raise ValueError('original phase helper dependency boundary differs')
    declarations = '\n'.join(f'void sub_{address:08x}(CPU *);' for address in sorted(set(FUNCTIONS) | references))
    (staged / 'generated.h').write_text(declarations + '\n', encoding='ascii')
    (staged / 'generated.c').write_text('#include "cpu.h"\n#include "generated.h"\n' + '\n'.join(bodies), encoding='ascii')


def _run(staged):
    compiler = subprocess.run(['clang', '--version'], capture_output=True, timeout=10)
    if compiler.returncode:
        raise ValueError('native clang is unavailable')
    command = ['clang', '-O1', '-fno-strict-aliasing', '-I' + str(ROOT / 'runtime'), '-I' + str(staged),
               str(ROOT / 'tools/hq_phase_driver.c'), str(staged / 'generated.c'),
               str(ROOT / 'runtime/hq_config.c'), '-lm', '-o', str(staged / 'phase-driver')]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if compiled.returncode:
        raise ValueError('phase driver compilation failed: ' + compiled.stderr[-4000:])
    executed = subprocess.run([str(staged / 'phase-driver'), str(staged / 'baseline.game.bin'),
                               str(staged / 'module.memory.bin'), str(staged / 'selected.ini'),
                               str(staged / 'callback.game.bin'), str(staged / 'render.game.bin')],
                              capture_output=True, text=True, timeout=15)
    (staged / 'driver.log').write_text(executed.stdout + executed.stderr)
    if executed.returncode:
        raise ValueError(f'original phase driver refused execution ({executed.returncode}): ' + executed.stderr[-2000:])
    return {'compiler': 'clang', 'version_sha256': _sha(compiler.stdout + compiler.stderr),
            'flags': ['-O1', '-fno-strict-aliasing'], 'alarm_seconds': 10}


def _ranges(before, after, allowed):
    if len(after) != GAME_SIZE:
        raise ValueError('phase output is not a complete mapped game image')
    changed = []
    for offset, (old, new) in enumerate(zip(before, after)):
        if old == new:
            continue
        address = GAME_BASE + offset
        if not any(start <= address < start + size for start, size in allowed):
            raise ValueError(f'phase wrote outside its original code operands: {address:08x}')
        if changed and changed[-1][0] + changed[-1][1] == address:
            changed[-1][1] += 1
        else:
            changed.append([address, 1])
    return changed


def _branch(memory, address, opcode, target):
    at = address - GAME_BASE
    if memory[at] != opcode or address + 5 + int.from_bytes(memory[at + 1:at + 5], 'little', signed=True) != target:
        raise ValueError(f'original phase branch differs at {address:08x}')


def _snapshots(staged, canonical):
    baseline = (staged / 'baseline.game.bin').read_bytes()
    callback = (staged / 'callback.game.bin').read_bytes()
    render = (staged / 'render.game.bin').read_bytes()
    changes = [_ranges(baseline, callback, CALLBACK_RANGES), _ranges(callback, render, RENDER_RANGES)]
    _branch(callback, 0x005a30b1, 0xe8, 0x010160e0)
    for address, opcode, target in BRANCHES:
        _branch(render, address, opcode, target)
    game = pefile.PE(str(canonical)).get_memory_mapped_image()
    at = 0x006de9f8 - GAME_BASE
    if render[at:at + 8] != game[at:at + 8]:
        raise ValueError('original renderer restoration differs')
    return [{'phase': name, 'file': name + '.game.bin', 'size': len(data), 'sha256': _sha(data), 'changed_ranges': ranges}
            for name, data, ranges in zip(('callback', 'render'), (callback, render), changes)]


def prepare_phases(game_root, baseline_game_memory, output, *, baseline_sha256):
    """Return raw callback/render snapshots layered on a trusted upstream capture.

    The caller authenticates the upstream preparation manifest and supplies its
    baseline digest. This verifies that digest and the canonical PE header; it
    does not authenticate an arbitrary caller-supplied code modification.
    """
    output = _output(output)
    profile = options(os.environ)
    if (any(profile[key] for key in ('WATCH', 'JTSWITCH', 'LREGS', 'X87OPT', 'FTOL2INL', 'NOCLOSURE')) or
            not profile['FLAGOPT'] or not profile['RETEIP'] or profile['INLINE'] or
            profile['CODE_RVA_START'] is not None or os.environ.get('FLAGABI')):
        raise ValueError('unsupported generation environment for bounded phase preparation')
    profile.update(COMMENTS=True, X87PC=True, OVERRIDE=list(STOP_SITES), SYMPFX='')
    inputs = _inputs(game_root, baseline_game_memory, baseline_sha256)
    game_root = Path(game_root).resolve()
    if output.is_relative_to(game_root) or game_root.is_relative_to(output) or any(path.resolve().is_relative_to(output) for path in inputs.values()):
        raise ValueError('phase output overlaps its game or capture inputs')
    digests = {key: _sha(path.read_bytes()) for key, path in inputs.items()}
    processors = _processors()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.hq-phases-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'prepared'
        staged.mkdir()
        shutil.copyfile(inputs['baseline'], staged / 'baseline.game.bin')
        shutil.copyfile(inputs['config'], staged / 'selected.ini')
        _generate(inputs['module'], staged)
        native_driver = _run(staged)
        snapshots = _snapshots(staged, inputs['canonical'])
        if processors != _processors() or digests != {key: _sha(path.read_bytes()) for key, path in inputs.items()}:
            raise ValueError('phase inputs or processors changed during preparation')
        record = {'version': 1, 'producer': 'hq-phases', 'baseline_sha256': baseline_sha256,
                  'canonical_sha256': digests['canonical'], 'module_sha256': digests['module'],
                  'config_sha256': digests['config'], 'processors': processors,
                  'generation': profile, 'native_driver': native_driver, 'versions': {'python': sys.version.split()[0], 'capstone': version('capstone'), 'pefile': version('pefile')},
                  'stop_sites': list(STOP_SITES), 'functions': list(FUNCTIONS), 'snapshots': snapshots,
                  'artifacts': {path.name: _sha(path.read_bytes()) for path in sorted(staged.iterdir())}}
        (staged / MARKER).write_text(json.dumps(record, indent=2) + '\n', encoding='ascii')
        _output(output)
        previous = Path(temporary) / 'previous'
        if output.exists():
            output.rename(previous)
        try:
            staged.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise
    return [output / row['file'] for row in snapshots]
