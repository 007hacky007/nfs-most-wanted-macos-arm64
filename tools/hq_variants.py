"""Prepare separate HQ data trees while preserving the standard installation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile

try:
    from .extract_hq import safe_relative, sha256
    from .runtime_image import HQ_IMAGE_SHA256, STANDARD_RUNTIME_SHA256, build_standard_runtime
except ImportError:
    from extract_hq import safe_relative, sha256
    from runtime_image import HQ_IMAGE_SHA256, STANDARD_RUNTIME_SHA256, build_standard_runtime

HQ_RUNTIME_SHA256 = HQ_IMAGE_SHA256
RUNTIME_SHA256 = STANDARD_RUNTIME_SHA256
MODERN_SHADERS = (
    'car', 'debugPoly', 'glassreflectshader', 'grass', 'hdr', 'particles',
    'shadowscreenfilter', 'shadowvolume', 'sky', 'standard', 'trees', 'visualtreatment',
    'waterseashader', 'world', 'worldbone', 'worldnormalmap', 'worldreflect',
)
FULL_MODS = (
    'X360Stuff 4.1', 'MWFixes', 'WidescreenFix', 'XboxRainDroplets', 'ExtraOptions 10.0.1.1337',
    'FEShadows 2.1', 'HDContentSupport 2.0', 'HDReflections 2.0', 'HUDAdapter',
    'MotionBlurController 1.0.0.100', 'Unlimiter 3.3.0.1338', 'XenonEffects',
    'SpeedReflect 1.2', 'TexWizard', 'ZPatchMW',
)
# CurStepChanged disassembly: modern 0x00732, lighting 0x060D4, database 0x0F428.
FULL_COPIES = (
    ('LOGIC/41/DYNTEX.BIN', 'GLOBAL/DYNTEX.BIN'),
    ('LOGIC/41/InGameA.bun', 'GLOBAL/InGameA.bun'),
    ('LOGIC/41/X360Stuff.asi', 'scripts/X360Stuff.asi'),
    ('LOGIC/41/X360Stuff.pdb', 'scripts/X360Stuff.pdb'),
    *((f'LOGIC/41/FX/{name}.fx.o', f'FX/COMPILED/{name}.fx.o') for name in MODERN_SHADERS),
    ('LOGIC/360osd/GlobalB.lzc', 'GLOBAL/GlobalB.lzc'),
    ('LOGIC/360osd/InGameA.bun', 'GLOBAL/InGameA.bun'),
    *((f'LOGIC/360osd/{name}', f'GLOBAL/{name}')
      for name in ('attributes.bin', 'gameplay.bin', 'gameplay.lzc')),
)
FULL_INI = {
    'scripts/NFSMostWanted.WidescreenFix.ini': {
        'HUDWidescreenMode': '0', 'FMVWidescreenMode': '0', 'WriteSettingsToFile': '1',
        'ShadowsRes': '4096', 'ImproveShadowLOD': '1', 'SkipIntro': '0',
    },
    'scripts/X360Stuff.ini': {'UseFullLODShaderOnTrafficAndCops': '1'},
    'scripts/NFSMWHDReflections.ini': {
        'AutoRes': '1', 'ImproveReflectionLOD': '1', 'RestoreWaterReflections': '1',
    },
    'scripts/NFSMWExtraOptionsSettings.ini': {'SkipMovies': '0', 'SkipNISs': '0'},
}
PRELOAD_CACHES = ('GlobalMemoryFile.bin', 'InGameMemoryFile.bin',
                  'PermanentMemoryFile.bin', 'FrontEndMemoryFile.bin',
                  'CarHeadersMemoryFile.bin')
EMPTY_PRELOAD_CACHE = struct.pack('<4I', 0, 0, 0x53219999, 0)


def case_path(root, relative):
    """Resolve each existing path component without assuming filesystem case rules."""
    current = Path(root)
    for part in safe_relative(relative).parts:
        matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()] if current.is_dir() else []
        if len(matches) > 1:
            raise ValueError(f'ambiguous case collision: {relative}')
        current = matches[0] if matches else current / part
        if current.is_symlink():
            raise ValueError('variant symlinks are unsupported')
    return current


def verify_runtime(path, expected=None):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != (expected or HQ_RUNTIME_SHA256):
        raise ValueError('unsupported runtime SHA-256')
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('HQ runtime is not a PE executable')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if data[offset:offset + 6] != b'PE\0\0\x4c\x01':
        raise ValueError('HQ runtime must be an i386 PE image')


def overlay(source, root, relative):
    target = case_path(root, relative)
    if target.suffix.casefold() in ('.bun', '.bin'):
        compressed = case_path(root, str(safe_relative(relative).with_suffix('.lzc')))
        if compressed.is_file():
            compressed.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def selected_files(manifest):
    """Apply English and the original-playlist choice, leaving no ambiguous aliases."""
    selected = {name: name for name in manifest['files'] if '$' not in name and '#' not in name}
    for canonical, choices in manifest.get('variants', {}).items():
        choice = next((name for name in choices if name.endswith('#lang-en')), None)
        if choice is None and canonical.casefold() in ('sound/pfdata/mw_music.mpf', 'sound/pfdata/mw_music.mus'):
            choice = next((name for name in choices if name.endswith('$0')), None)
        if choice is None:
            raise ValueError(f'no explicit default for HQ variant: {canonical}')
        selected[canonical] = choice
    return selected


def invalidate_preload_caches(root):
    """Discard cached stock file prefixes after replacing geometry or textures."""
    changed = {}
    for name in PRELOAD_CACHES:
        path = case_path(root, 'GLOBAL/' + name)
        if not path.is_file():
            continue
        with path.open('rb') as file:
            header = file.read(16)
        if len(header) != 16 or header[:12] != EMPTY_PRELOAD_CACHE[:12]:
            raise ValueError(f'unsupported preload cache header: {name}')
        # Cached WHEELS offsets otherwise address the replacement file using
        # the stock layout. A zero-entry cache makes the game read its files.
        path.write_bytes(EMPTY_PRELOAD_CACHE)
        changed[path.relative_to(root).as_posix()] = sha256(path)
    return changed


def build_variants(base: Path, hq_source: Path) -> dict:
    """Create base/.nfsmw/{visuals,full}, runtime.exe and variants.json.

    The launcher also checks that its executable includes the native HQ modules.
    """
    base, hq_source = Path(base).resolve(), Path(hq_source).resolve()
    if not base.is_dir() or not (base / 'speed.exe').is_file():
        raise ValueError('standard installation is missing speed.exe')
    source_manifest = json.loads((hq_source / '.hq-manifest.json').read_text())
    if source_manifest.get('version') != '1.20.9':
        raise ValueError('unsupported HQ source manifest version')
    selected = selected_files(source_manifest)
    index = {name.casefold(): name for name in source_manifest['files']}
    verified = set()

    def source(name):
        key = index.get(str(safe_relative(name)).casefold())
        if key is None:
            raise ValueError(f'required HQ file missing: {name}')
        path = case_path(hq_source, key)
        if key not in verified:
            if not path.is_file() or sha256(path) != source_manifest['files'][key]['sha256']:
                raise ValueError(f'HQ source hash mismatch: {key}')
            verified.add(key)
        return path

    runtime = source('LOGIC/41/speed.exe')
    verify_runtime(runtime)
    managed = base / '.nfsmw'
    if managed.is_symlink():
        raise ValueError('managed HQ directory cannot be a symlink')
    managed.mkdir(exist_ok=True)
    for mode in ('visuals', 'full'):
        if (managed / mode).exists():
            raise FileExistsError(f'{mode} variant already exists; keeping it untouched')
    def ignore_managed(directory, names):
        ignored = {'.nfsmw'} if Path(directory) == base else set()
        for name in set(names) - ignored:
            if (Path(directory) / name).is_symlink():
                raise ValueError('standard installation symlinks are unsupported')
        return ignored

    before = sha256(base / 'speed.exe')
    result = {'version': '1.20.9', 'runtime': {'path': '.nfsmw/runtime.exe', 'sha256': RUNTIME_SHA256},
              'variants': {}}
    with tempfile.TemporaryDirectory(prefix='.hq-variants-', dir=managed) as temporary:
        temporary = Path(temporary)
        staged_runtime = temporary / 'runtime.exe'
        build_standard_runtime(runtime, base / 'speed.exe', staged_runtime)
        for mode in ('visuals', 'full'):
            root = temporary / mode
            shutil.copytree(base, root, ignore=ignore_managed)
            applied = {}
            for canonical, original in selected.items():
                parts = safe_relative(canonical).parts
                directory = parts[0].casefold()
                if directory == 'logic':
                    continue
                if mode == 'visuals':
                    allowed = directory in ('cars', 'tracks', 'tex')
                    if directory == 'cars' and len(parts) > 2:
                        allowed = case_path(base, '/'.join(parts[:2])).is_dir()
                    if not allowed or canonical.casefold().endswith('.texed_cache'):
                        continue
                target = overlay(source(original), root, canonical)
                applied[target.relative_to(root).as_posix()] = sha256(target)
            if mode == 'visuals':
                applied.update(invalidate_preload_caches(root))
            if mode == 'full':
                for original, canonical in FULL_COPIES:
                    target = overlay(source(original), root, canonical)
                    applied[target.relative_to(root).as_posix()] = sha256(target)
                for relative, values in FULL_INI.items():
                    target = case_path(root, relative)
                    text = target.read_text()
                    for key, value in values.items():
                        text, count = re.subn(rf'(?m)^(\s*{re.escape(key)}\s*=\s*)[^\s;/]+',
                                              lambda match: match[1] + value, text)
                        if count != 1:
                            raise ValueError(f'expected exactly one {key} in {relative}')
                    target.write_text(text)
                    applied[target.relative_to(root).as_posix()] = sha256(target)
            target = overlay(staged_runtime if mode == 'visuals' else runtime, root, 'speed.exe')
            applied['speed.exe'] = sha256(target)
            required = list(FULL_MODS) if mode == 'full' else ['TexWizard', 'HDContentSupport']
            ready = True
            result['variants'][mode] = {'path': f'.nfsmw/{mode}', 'ready': ready,
                                       'required_mods': required,
                                       'pending': [] if ready else required + ['Race validation'],
                                       'files': applied}
        verify_runtime(staged_runtime, RUNTIME_SHA256)
        if sha256(base / 'speed.exe') != before:
            raise ValueError('standard executable changed while preparing HQ variants')
        staged_runtime.replace(managed / 'runtime.exe')
        for mode in ('visuals', 'full'):
            (temporary / mode).rename(managed / mode)
        staged_manifest = temporary / 'variants.json'
        staged_manifest.write_text(json.dumps(result, indent=2) + '\n')
        staged_manifest.replace(managed / 'variants.json')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('hq_source', type=Path)
    args = parser.parse_args()
    result = build_variants(args.base, args.hq_source)
    print(json.dumps({mode: {'files': len(item['files']), 'ready': item['ready']}
                      for mode, item in result['variants'].items()}))
