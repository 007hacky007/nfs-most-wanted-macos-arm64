"""Derive native lifecycle adapters from verified local AOT module preparation."""
import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import shutil
import tempfile
import sys

try:
    from .hq_module_catalog import MODULES,render_c_catalog
    from .prepare_hq_modules import processor_hashes
    from .generation_manifest import options,tool_hashes
except ImportError:
    from hq_module_catalog import MODULES,render_c_catalog
    from prepare_hq_modules import processor_hashes
    from generation_manifest import options,tool_hashes

MARKER='.hq-runtime.json'
PREPARED='.hq-generated.json'


def module_profile(module):
    environment={'COMMENTS':'1','X87PC':'1','RETEIP':'1','FLAGOPT':'1',
                 'JTSWITCH':'0'if module.module_id==1 else'1','SYMPFX':module.prefix}
    if module.code_rva_start is not None:environment['CODE_RVA_START']=str(module.code_rva_start)
    return options(environment)


def generation_versions():
    return {'python':sys.version.split()[0],'capstone':version('capstone'),'pefile':version('pefile')}


def validate_preparation(record,module):
    try:
        raw=record['raw_generation']
        valid=(record['key']==module.key and record['sha256']==module.sha256 and
               record['module']==json.loads(json.dumps(asdict(module))) and
               record['processors']==processor_hashes() and raw['version']==1 and
               raw['tools']==tool_hashes() and raw['versions']==generation_versions() and
               raw['options']==module_profile(module) and not raw['hooks'] and not raw['branches'] and
               set(raw['auxiliary'])=={'RELOCS','SEEDS'})
    except (KeyError,TypeError):valid=False
    if not valid:raise ValueError(f'module preparation provenance differs: {module.key}')


def verify_runtime(source=Path('gen/hq-runtime'),modules=MODULES):
    """Refuse stale or edited adapters before compiling their native modules."""
    source=Path(source);modules=tuple(modules)
    if source.is_symlink()or(source/MARKER).is_symlink():raise ValueError('runtime root symlinks are unsupported')
    record=json.loads((source/MARKER).read_text())
    if record.get('version')!=2 or record.get('adapter_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('stale runtime adapter; prepare HQ runtime again')
    catalog=render_c_catalog(modules).encode('ascii')
    if ((source/'catalog.inc').is_symlink()or(source/'catalog.inc').read_bytes()!=catalog or
            record.get('catalog_sha256')!=hashlib.sha256(catalog).hexdigest()):
        raise ValueError('runtime catalog differs')
    identities=[(module.key,module.sha256)for module in modules]
    if [(row['key'],row['sha256'])for row in record['modules']]!=identities:
        raise ValueError('runtime module identity differs')
    sources=[]
    for module,row in zip(modules,record['modules']):
        marker=row['prepared_marker']
        if hashlib.sha256(marker.encode()).hexdigest()!=row['prepared_marker_sha256']:
            raise ValueError('runtime prepared marker differs')
        validate_preparation(json.loads(marker),module)
        folder=source/row['key']
        if folder.is_symlink():raise ValueError('runtime module symlink is unsupported')
        for name,digest in row['artifacts'].items():
            if Path(name).name!=name:raise ValueError('invalid runtime artifact name')
            path=folder/name
            if path.is_symlink()or not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError(f'runtime artifact differs: {row["key"]}/{name}')
            if path.suffix=='.c':sources.append(f'{row["key"]}/{name}')
    if sorted(sources)!=sorted(record['sources'])or len(set(sources))!=len(sources):
        raise ValueError('runtime source inventory differs')
    return record


def adapt_sources(key,sources):
    """Return copies; exact expected boundaries must occur once before any output."""
    result=dict(sources)
    def replace(old,new):
        matches=sum(text.count(old)for name,text in result.items()if name.startswith('shard'))
        if matches!=1:raise ValueError(f'{key}: expected one adapter boundary: {old}')
        for name,text in result.items():
            if name.startswith('shard')and old in text:result[name]=text.replace(old,new,1)
    def rename(address):
        replace(f'void sub_{address:08x}(CPU *restrict c) {{',f'void sub_{address:08x}_body(CPU *restrict c) {{')
    def remove(address):
        pattern=re.compile(r'^/\* ===== sub_'+f'{address:08x}'+r'\b.*?(?=^/\* ===== sub_|\Z)',re.M|re.S)
        count=0
        for name,text in result.items():
            if name.startswith('shard'):
                text,n=pattern.subn(f'/* Native config adapter for {address:08x}. */\n',text)
                result[name]=text;count+=n
        if count!=1:raise ValueError(f'{key}: expected one config adapter boundary')
    if key=='x360':
        remove(0x01007e80)
        for address in (0x01007cb0,0x01013660,0x01007b10,0x01007b30,0x01016f10):rename(address)
        marker='    /* 01016f53  mov ecx, dword ptr [ebp - 8] */'
        replace(marker,'    hq_video_resolution(c->ebp-8,c->ebp-4);\n'+marker)
        for name,text in result.items():
            if 'hq_video_resolution(c->ebp-8' in text:
                result[name]='#include <stdint.h>\nvoid hq_video_resolution(uint32_t,uint32_t);\n'+text
    elif key=='unlimiter':
        rename(0x01809740)
        marker='    DISPATCH_TAIL(c, 0x756aadu);'
        replace(marker,'    hq_plugin_checkpoint(c,1);\n'+marker)
        for name,text in result.items():
            if 'hq_plugin_checkpoint(c,1);'in text:result[name]='#include "hq_plugin.h"\n'+text
    elif key=='extraoptions':rename(0x01c04a50)
    elif key=='xenon':remove(0x024030f0)
    return result


def prepare_runtime(source=Path('gen/hq'),output=Path('gen/hq-runtime'),modules=MODULES):
    source,output=Path(source),Path(output);modules=tuple(modules)
    adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if source.resolve()==output.resolve()or source.resolve().is_relative_to(output.resolve())or output.resolve().is_relative_to(source.resolve()):
        raise ValueError('runtime and prepared module roots must not overlap')
    if source.is_symlink()or output.is_symlink():raise ValueError('module root symlinks are unsupported')
    if output.exists()and(not(output/MARKER).is_file()or(output/MARKER).is_symlink()):
        raise ValueError('refusing to replace unmanaged runtime output')
    expected_catalog=render_c_catalog(modules)
    if(source/'catalog.inc').is_symlink()or(source/'catalog.inc').read_text()!=expected_catalog:
        raise ValueError('module catalog differs from selected prepared modules')
    prepared=[]
    for module in modules:
        folder=source/module.key;marker=folder/PREPARED
        if folder.is_symlink()or marker.is_symlink():raise ValueError('prepared module symlink is unsupported')
        record=json.loads(marker.read_text())
        validate_preparation(record,module)
        if record['key']!=module.key or record['sha256']!=module.sha256 or record['module']!=json.loads(json.dumps(asdict(module))):
            raise ValueError(f'prepared module identity differs: {module.key}')
        artifacts=record['artifacts'];sources={}
        for name,digest in artifacts.items():
            if Path(name).name!=name:raise ValueError('invalid prepared artifact name')
            path=folder/name
            if path.is_symlink()or not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError(f'prepared artifact differs: {module.key}/{name}')
            if path.suffix in ('.c','.h','.inc'):sources[name]=path.read_text()
        prepared.append((module,record,adapt_sources(module.key,sources),marker.read_text()))
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.hq-runtime-',dir=output.parent)as temporary:
        staged=Path(temporary)/'generated';staged.mkdir();records=[];source_list=[]
        for module,record,sources,marker in prepared:
            folder=staged/module.key;folder.mkdir()
            for name,text in sources.items():(folder/name).write_text(text,encoding='ascii')
            files={name:hashlib.sha256((folder/name).read_bytes()).hexdigest()for name in sorted(sources)}
            records.append({'key':module.key,'sha256':module.sha256,'prepared_marker':marker,
                            'prepared_marker_sha256':hashlib.sha256(marker.encode()).hexdigest(),'artifacts':files})
            source_list.extend(f'{module.key}/{name}'for name in sorted(sources)if name.endswith('.c'))
        (staged/'catalog.inc').write_text(expected_catalog,encoding='ascii')
        manifest={'version':2,'adapter_sha256':adapter_sha256,
                  'modules':records,'sources':source_list,'catalog_sha256':hashlib.sha256(expected_catalog.encode('ascii')).hexdigest()}
        (staged/MARKER).write_text(json.dumps(manifest,indent=2)+'\n',encoding='ascii')
        # Recheck inputs before replacing the generated cache.
        for module,record,_,marker in prepared:
            validate_preparation(record,module)
            if json.loads((source/module.key/PREPARED).read_text())!=record:raise ValueError('prepared marker changed')
            for name,digest in record['artifacts'].items():
                if hashlib.sha256((source/module.key/name).read_bytes()).hexdigest()!=digest:raise ValueError('prepared artifact changed')
        if adapter_sha256!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ValueError('runtime adapter changed during preparation')
        if output.exists():shutil.rmtree(output)
        shutil.move(str(staged),str(output))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('gen/hq'))
    parser.add_argument('--output',type=Path,default=Path('gen/hq-runtime'))
    args=parser.parse_args();record=prepare_runtime(args.source,args.output)
    print('Prepared runtime modules:',len(record['modules']),'sources:',len(record['sources']))
