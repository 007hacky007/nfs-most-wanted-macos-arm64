"""Bind native generation to its inputs without storing local paths or guest code."""
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='generation-manifest.json'
TOOL_FILES=('tools/generation_manifest.py','tools/genall.py','tools/lift.py',
            'tools/game_code_data.py','tools/lregs.py','tools/retpast.txt','runtime/cpu.h','runtime/target.h')
BOOL_OPTIONS=('COMMENTS','WATCH','COVERAGE','JTSWITCH','LREGS','X87OPT','X87PC',
              'FTOL2INL','NOCLOSURE')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized_hooks(text):
    addresses=sorted({int(value,16) for value in text.split(',') if value.strip()})
    if any(not 0<=address<=0xffffffff for address in addresses):
        raise ValueError('invalid generation hook address')
    return addresses


def normalized_branches(text):
    branches={}
    for value in text.split(','):
        if not value.strip():continue
        pair=value.split(':')
        if len(pair)!=2:raise ValueError('invalid generation branch')
        source,target=(int(x,16) for x in pair)
        if source in branches or not 0<=source<=0xffffffff or not 0<=target<=0xffffffff:
            raise ValueError('invalid generation branch')
        branches[source]=target
    return [[source,target] for source,target in sorted(branches.items())]


def tool_hashes():
    return {name:digest(ROOT/name) for name in TOOL_FILES}


def options(environment):
    values={name:environment.get(name,'')=='1' for name in BOOL_OPTIONS}
    values.update({name:environment.get(name,'1')!='0' for name in ('FLAGOPT','RETEIP')})
    values['INLINE']=int(environment.get('INLINE','0') or '0')
    values['CODE_RVA_START']=int(environment['CODE_RVA_START'],0) if environment.get('CODE_RVA_START') else None
    values['OVERRIDE']=normalized_hooks(environment.get('OVERRIDE',''))
    prefix=environment.get('SYMPFX','')
    if prefix and not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',prefix):
        raise ValueError('invalid generation symbol prefix')
    values['SYMPFX']=prefix
    return values


def input_record(exe,hooks,branches,environment):
    auxiliary={'RELOCS':environment.get('RELOCS','out/relocs.txt')}
    auxiliary.update({name:environment[name] for name in ('SEEDS','INLINE_LIST','FLAGABI') if environment.get(name)})
    return {'version':1,'exe_sha256':digest(exe),
            'hooks':normalized_hooks(hooks if hooks is not None else environment.get('HOOKS','')),
            'branches':normalized_branches(branches if branches is not None else environment.get('BRANCH_HOOKS','')),
            'options':options(environment),'auxiliary':{name:digest(path) for name,path in auxiliary.items()},
            'tools':tool_hashes(),'versions':{'python':sys.version.split()[0],
                'capstone':version('capstone'),'pefile':version('pefile')}}


@dataclass
class GenerationCapture:
    exe: Path
    hooks: object
    branches: object
    environment: object
    record: dict


def capture_generation(exe,*,hooks=None,branches=None,environment=None):
    """Call before discovering functions or changing generated output."""
    environment=os.environ if environment is None else environment
    return GenerationCapture(Path(exe),hooks,branches,environment,
                             input_record(exe,hooks,branches,environment))


def artifact_hashes(generated):
    generated=Path(generated)
    paths=sorted(generated.glob('shard_*.c'))
    if not paths:raise ValueError('generation has no shards')
    paths.extend(generated/name for name in ('decls.h','fntab.c'))
    if (generated/'stubs.c').exists() or (generated/'stubs.c').is_symlink():paths.append(generated/'stubs.c')
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError('generation artifact is missing or a symlink')
    return {path.name:digest(path) for path in paths}


def write_generation(generated,capture):
    """Publish only after checking that generation inputs stayed unchanged."""
    artifacts=artifact_hashes(generated)
    try:
        current=input_record(capture.exe,capture.hooks,capture.branches,capture.environment)
    except (OSError,ValueError) as error:
        raise ValueError('generation inputs changed before publication') from error
    if current!=capture.record:raise ValueError('generation inputs changed before publication')
    result=dict(current,artifacts=artifacts)
    generated=Path(generated)
    with tempfile.NamedTemporaryFile(mode='w',dir=generated,prefix='.generation-',delete=False) as stream:
        temporary=Path(stream.name)
        try:
            json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush()
            os.replace(temporary,generated/MANIFEST)
        finally:
            temporary.unlink(missing_ok=True)
    return result


def record_generation(generated,exe,hook_file,branch_file):
    """Immediate capture/write for synthetic fixtures, not existing production caches."""
    return write_generation(generated,capture_generation(exe,
        hooks=Path(hook_file).read_text(),branches=Path(branch_file).read_text()))


def verify_generation(generated,exe,hook_file,branch_file):
    """Reject stale baseline inputs or outputs before a consumer changes its cache."""
    try:
        path=Path(generated)/MANIFEST
        if path.is_symlink():raise ValueError('generation manifest is a symlink')
        record=json.loads(path.read_text())
        if (set(record)!={'version','exe_sha256','hooks','branches','options','auxiliary','tools','versions','artifacts'} or
                set(record['options'])!=set(options({})) or 'RELOCS' not in record['auxiliary'] or
                record['version']!=1 or record['exe_sha256']!=digest(exe) or
                record['hooks']!=normalized_hooks(Path(hook_file).read_text()) or
                record['branches']!=normalized_branches(Path(branch_file).read_text()) or
                record['tools']!=tool_hashes() or record['artifacts']!=artifact_hashes(generated) or
                record['versions']!={'python':sys.version.split()[0],
                    'capstone':version('capstone'),'pefile':version('pefile')}):
            raise ValueError('generation provenance does not match inputs or artifacts')
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as error:
        raise ValueError('generation provenance is missing or invalid') from error
    return record
