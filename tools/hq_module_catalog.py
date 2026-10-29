"""Pinned module identities and lifecycle metadata; contains no guest code."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re


@dataclass(frozen=True)
class TLS:
    index: int
    start: int
    size: int
    index_address: int


@dataclass(frozen=True)
class Initializer:
    entry: int
    timing: str


@dataclass(frozen=True)
class Module:
    key: str
    module_id: int
    path: str
    sha256: str
    size: int
    base: int
    image_size: int
    entry: int
    prefix: str
    tls: TLS | None = None
    init: tuple[Initializer, ...] = ()
    wrappers: tuple[int, ...] = ()
    code_rva_start: int | None = None


MODULES = (
    Module('d3dx',1,'d3dx9_26.dll',
           '8ea96fe01c3c86a36fcb3795ae03eb12034003e335ef475571efaeda17c5bc78',
           2297552,0x02000000,0x24a000,0x021fff6c,'dx_',
           code_rva_start=0x2a005),
    Module('x360',2,'scripts/X360Stuff.asi',
           '0073249a7642a3c1d8bd196c5795cc22da8eb8218349762301ba66b686c00fe8',
           192512,0x01000000,0x36000,0x010071a2,'x360_',
           TLS(128,0x01020748,8,0x0102f644),
           (Initializer(0x01007cb0,'before_game'),Initializer(0x01013660,'device_ready'),
            Initializer(0x01007b30,'game_startup')),
           (0x01007cb0,0x01013660,0x01007b10,0x01007b30,0x01016f10)),
    Module('rain',3,'scripts/NFSMostWanted.XboxRainDroplets.asi',
           'cf0cb791ae402447eeff272cb7073aa0d4975b0eb17594038776e286b8dcbc8c',
           125440,0x01400000,0x34000,0x014067bf,'rain_',
           TLS(129,0x0141c1a0,8,0x0142fe60),
           (Initializer(0x01404380,'before_game'),)),
    Module('unlimiter',4,'scripts/NFSMWUnlimiter.asi',
           'b35247cbd012ed89b011d781014d646c57b16eb085746cbb8aff98673791500f',
           293888,0x01800000,0x4d000,0x01814c74,'unlimiter_',
           TLS(130,0x01842334,8,0x01846660),
           (Initializer(0x0180eb30,'crt_callback'),),(0x01809740,)),
    Module('extraoptions',5,'scripts/NFSMWExtraOptions.asi',
           '32bc3ae6c3f36218ae507b666d8fb816c2263fdb7819498286bca11537ec8ff2',
           278528,0x01c00000,0x48000,0x01c0fe6f,'extraopts_',
           TLS(131,0x01c3ede0,8,0x01c426f0),
           (Initializer(0x01c097f0,'crt_callback'),),(0x01c04a50,)),
    Module('xenon',6,'scripts/NFSMW_XenonEffects.asi',
           '5dcad612125be0f13426644b044a2a18874fc2d84726c033e97975e262256692',
           72192,0x02400000,0x16000,0x0240ab2e,'xenon_',
           TLS(132,0x024108d8,8,0x02413744),
           (Initializer(0x02404940,'game_startup'),)),
)

CATALOG_MARKER='/* Module catalog from tools/hq_module_catalog.py. */'


def render_c_catalog(modules=MODULES):
    """C macro rows contain module identifiers and TLS metadata only."""
    modules=tuple(modules);validate_catalog(modules)
    rows=[CATALOG_MARKER]
    for module in modules:
        tls=module.tls
        fields=(f'{tls.index}u',f'0x{tls.start:08x}u',f'{tls.size}u',f'0x{tls.index_address:08x}u')if tls else(
            'UINT32_MAX','0u','0u','0u')
        rows.append(f'HQ_MODULE({module.prefix},'+','.join(fields)+')')
    return '\n'.join(rows)+'\n'


def validate_catalog(modules):
    ids=set();keys=set();prefixes=set();slots=set();ranges=[]
    for module in modules:
        if (not re.fullmatch('[a-z][a-z0-9_]*',module.key)or
                not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',module.prefix)):
            raise ValueError('invalid module identifier')
        if module.module_id in ids or module.key in keys or module.prefix in prefixes:
            raise ValueError('duplicate module identity')
        ids.add(module.module_id);keys.add(module.key);prefixes.add(module.prefix)
        if (module.base%0x10000 or module.base<0x01000000 or module.image_size<=0 or
                module.base+module.image_size>0x03000000):
            raise ValueError('module overlaps a reserved guest range')
        for start,end in ranges:
            if module.base<end and start<module.base+module.image_size:
                raise ValueError('module address ranges overlap')
        ranges.append((module.base,module.base+module.image_size))
        for entry in (module.entry,*(item.entry for item in module.init),*module.wrappers):
            if not module.base<=entry<module.base+module.image_size:
                raise ValueError('entrypoint is outside the module')
        if module.tls:
            if module.tls.index in slots:raise ValueError('duplicate static TLS slot')
            slots.add(module.tls.index)
            for address,size in ((module.tls.start,module.tls.size),(module.tls.index_address,4)):
                if address<module.base or address+size>module.base+module.image_size:
                    raise ValueError('TLS metadata is outside the module')


def case_path(root,relative):
    path=Path(root)
    for part in Path(relative).parts:
        if part in ('..','/'):
            raise ValueError('invalid module path')
        if path.is_symlink():raise ValueError('module symlink is unsupported')
        matches=[p for p in path.iterdir()if p.name.casefold()==part.casefold()]if path.is_dir()else[]
        if len(matches)>1:raise ValueError('ambiguous module path')
        path=matches[0]if matches else path/part
    if path.is_symlink():raise ValueError('module symlink is unsupported')
    return path


def verify_inputs(game,modules=MODULES):
    """Verify every input before generation creates any output."""
    validate_catalog(modules);game=Path(game);paths=[]
    full=case_path(game,'.nfsmw/full')
    for module in modules:
        source=case_path(full if module.module_id!=1 and full.is_dir()else game,module.path)
        if not source.is_file():raise ValueError(f'required module missing: {module.path}')
        raw=source.read_bytes()
        if len(raw)!=module.size or hashlib.sha256(raw).hexdigest()!=module.sha256:
            raise ValueError(f'unsupported module SHA-256: {module.path}')
        paths.append(source)
    return paths
