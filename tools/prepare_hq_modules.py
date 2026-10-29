#!/usr/bin/env python3
"""Generate local native module sources from verified user-supplied binaries."""
import argparse
import contextlib
import hashlib
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from .hq_module_catalog import MODULES, verify_inputs,render_c_catalog,CATALOG_MARKER
    from .prepare_module import main as prepare_image
    from .hq_game_references import normalize_register_returns
    from .hq_crt_environment import validate_extraoptions_environment,adapt_extraoptions_environment
except ImportError:
    from hq_module_catalog import MODULES, verify_inputs,render_c_catalog,CATALOG_MARKER
    from prepare_module import main as prepare_image
    from hq_game_references import normalize_register_returns
    from hq_crt_environment import validate_extraoptions_environment,adapt_extraoptions_environment

ROOT=Path(__file__).resolve().parents[1]
MARKER='.hq-generated.json'
ABI=json.loads((Path(__file__).with_name('hq_import_abi.json')).read_text())
ENTRYPOINTS=json.loads((Path(__file__).with_name('hq_entrypoints.json')).read_text())


def processor_hashes():
    names=('prepare_hq_modules.py','prepare_module.py','argcount.py','hq_module_catalog.py','hq_game_references.py',
           'hq_crt_environment.py','hq_entrypoints.json','hq_import_abi.json')
    return {name:hashlib.sha256((ROOT/'tools'/name).read_bytes()).hexdigest()for name in names}


def extra_entrypoints(module):
    """Address-only entrypoint metadata, bound to the binary it describes."""
    record=ENTRYPOINTS.get(module.key)
    if record is None:return ()
    rvas=record['rvas']
    if (record['sha256']!=module.sha256 or rvas!=sorted(set(rvas))or
            any(type(rva)is not int or not 0<=rva<module.image_size for rva in rvas)):
        raise ValueError(f'invalid module entrypoint metadata: {module.key}')
    return tuple(module.base+rva for rva in rvas)


def normalize_continuations(source,game_range=(0x00401000,0x0088f2a5)):
    """Preserve the caller frame for caves entering the supported game's .text."""
    records=[]
    pattern=(r'(/\* ([0-9a-f]{8})\b[^\n]*\*/\s*)PUSH32\(0x([0-9a-f]+)u\);\s*'
             r'/\* [0-9a-f]{8}\s+ret\s*\*/\s*POP32\(c->eip\); return;')
    def replace(match):
        site,target=int(match[2],16),int(match[3],16)
        if not game_range[0]<=target<game_range[1]:return match[0]
        records.append({'site':site,'target':target})
        return match[1]+f'DISPATCH_TAIL(c, 0x{target:x}u);'
    return re.sub(pattern,replace,source),records


def import_rows(source,module):
    import pefile
    pe=pefile.PE(str(source));delta=module.base-pe.OPTIONAL_HEADER.ImageBase;rows=[]
    if (pe.FILE_HEADER.Machine!=0x14c or not pe.FILE_HEADER.Characteristics&0x2000 or
            pe.OPTIONAL_HEADER.SizeOfImage!=module.image_size or
            module.base+pe.OPTIONAL_HEADER.AddressOfEntryPoint!=module.entry):
        raise ValueError(f'module PE metadata differs: {module.key}')
    text=next(section for section in pe.sections if section.Name.rstrip(b'\0')==b'.text')
    for address in extra_entrypoints(module):
        if not module.base+text.VirtualAddress<=address<module.base+text.VirtualAddress+text.Misc_VirtualSize:
            raise ValueError(f'module entrypoint is outside .text: {module.key}')
    tls=getattr(pe,'DIRECTORY_ENTRY_TLS',None)
    if module.tls:
        if not tls or (tls.struct.StartAddressOfRawData+delta,
                       tls.struct.EndAddressOfRawData-tls.struct.StartAddressOfRawData,
                       tls.struct.AddressOfIndex+delta,tls.struct.SizeOfZeroFill)!=(
                           module.tls.start,module.tls.size,module.tls.index_address,0):
            raise ValueError(f'module TLS metadata differs: {module.key}')
    elif tls:raise ValueError(f'unexpected static TLS: {module.key}')
    for library in getattr(pe,'DIRECTORY_ENTRY_IMPORT',[]):
        dll=library.dll.decode('ascii')
        for entry in library.imports:
            name=entry.name.decode('ascii')if entry.name else '#'+str(entry.ordinal)
            key=dll.lower()+'!'+name
            if module.module_id!=1 and key not in ABI:
                raise ValueError(f'no verified import cleanup for {dll}!{name}')
            rows.append({'iat':entry.address+delta,'dll':dll,'name':name,
                         'words':ABI.get(key)})
    return rows


def emit_imports(path,module,rows):
    lines=['#include <stdint.h>',
           'typedef struct {uint32_t iat;const char *dll,*name;int nargs;} ImpEnt;',
           f'const uint32_t g_{module.prefix}imp_count={len(rows)};',
           f'const ImpEnt g_{module.prefix}imp[]={{']
    for row in rows:
        lines.append(f'  {{0x{row["iat"]:08x}u,{json.dumps(row["dll"])},{json.dumps(row["name"])},{row["words"]}}},')
    lines.append('};');path.write_text('\n'.join(lines)+'\n')


def checked_output(path):
    path=Path(path).resolve()
    if path.is_relative_to(ROOT):
        relative=path.relative_to(ROOT)
        if not relative.parts or relative.parts[0]not in ('gen','out'):
            raise ValueError('generated game code must stay under ignored gen/ or out/')
    return path


def replace_generated(staged,destination,key):
    if destination.is_symlink():raise ValueError('generated module symlink is unsupported')
    if destination.exists():
        marker=destination/MARKER
        if destination.is_symlink()or not marker.is_file()or json.loads(marker.read_text()).get('key')!=key:
            raise ValueError(f'refusing to replace an unmanaged generated directory: {destination.name}')
        shutil.rmtree(destination)
    shutil.move(str(staged),str(destination))


def prepare_modules(game,out_root,gen_root,modules=MODULES,shards=16):
    """Prepare relocations, functions and strict import ABI; never execute guest code.

    Runtime-specific config/video adapters and guarded patched game functions
    are a separate stage. This preparation alone does not enable Full HQ.
    """
    processors=processor_hashes()
    modules=tuple(modules);sources=verify_inputs(game,modules)
    imports=[import_rows(source,module)for source,module in zip(sources,modules)]
    for source,module in zip(sources,modules):
        if module.key=='extraoptions':validate_extraoptions_environment(source.read_bytes(),module.base)
    out_root,gen_root=checked_output(out_root),checked_output(gen_root)
    if out_root.is_relative_to(gen_root)or gen_root.is_relative_to(out_root):
        raise ValueError('generated output directories must not overlap')
    catalog=gen_root/'catalog.inc'
    if catalog.is_symlink()or(catalog.exists()and(not catalog.is_file()or not catalog.read_text().startswith(CATALOG_MARKER+'\n'))):
        raise ValueError('refusing to replace an unmanaged module catalog')
    # Validate all destinations before changing an existing generated cache.
    for root in (out_root,gen_root):
        for module in modules:
            destination=root/module.key
            if destination.is_symlink():raise ValueError('generated module symlink is unsupported')
            if destination.exists():
                marker=destination/MARKER
                if (destination.is_symlink()or not marker.is_file()or marker.is_symlink()or
                        json.loads(marker.read_text()).get('key')!=module.key):
                    raise ValueError(f'unmanaged generated directory: {destination.name}')
    out_root.mkdir(parents=True,exist_ok=True);gen_root.mkdir(parents=True,exist_ok=True)
    result={'version':1,'modules':[]}
    for source,module,rows in zip(sources,modules,imports):
        with tempfile.TemporaryDirectory(prefix='.module-',dir=out_root)as temporary:
            temporary=Path(temporary);staged_out=temporary/'out';staged_gen=temporary/'gen'
            staged_out.mkdir()
            with(staged_out/'prepare.log').open('w')as log,contextlib.redirect_stdout(log):
                prepare_image(str(source),module.base,str(staged_out),str(staged_gen),module.prefix)
            if (staged_out/'sha256.txt').read_text().strip()!=module.sha256:
                raise ValueError(f'module changed during preparation: {module.key}')
            seeds=staged_out/'seeds.txt'
            entries={int(line,16)for line in seeds.read_text().split()}
            entries.update(extra_entrypoints(module))
            seeds.write_text(''.join(f'{address:08x}\n'for address in sorted(entries)))
            env=dict(os.environ)
            for name in ('OVERRIDE','HOOKS','BRANCH_HOOKS','FTOL2INL','FLAGABI','INLINE_LIST','CODE_RVA_START','LREGS'):
                env.pop(name,None)
            env.update(GENOUT=str(staged_gen),RELOCS=str(staged_out/'relocs.txt'),
                       SEEDS=str(staged_out/'seeds.txt'),SYMPFX=module.prefix,COMMENTS='1',
                       JTSWITCH='0'if module.module_id==1 else'1',X87PC='1',RETEIP='1',FLAGOPT='1',
                       INLINE='0',X87OPT='0',NOCLOSURE='0',WATCH='0',COVERAGE='0',LREGS='0',FTOL2INL='0')
            if module.code_rva_start is not None:env['CODE_RVA_START']=hex(module.code_rva_start)
            with(staged_out/'generate.log').open('w')as log:
                subprocess.run([sys.executable,str(ROOT/'tools/genall.py'),str(staged_out/'image.dll'),str(shards)],
                               env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            references=[]
            if module.module_id!=1:
                with(staged_out/'references.log').open('w')as log:
                    subprocess.run([sys.executable,str(ROOT/'tools/hq_game_references.py'),
                        str(staged_out/'image.dll'),str(staged_gen/'decls.h'),str(staged_out/'game-references.json')],
                        env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
                references=json.loads((staged_out/'game-references.json').read_text())
            if module.module_id==1:
                env.update(IMPDLL=str(source.resolve()),IMPOUT=str(staged_gen/'impargs.c'),STRICT='1')
                with(staged_out/'imports.log').open('w')as log:
                    subprocess.run([sys.executable,str(ROOT/'tools/argcount.py'),str(staged_out/'image.dll')],
                                   env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
            else:emit_imports(staged_gen/'impargs.c',module,rows)
            if module.key=='extraoptions':
                shard_sources={path.name:path.read_text()for path in staged_gen.glob('shard_*.c')}
                for name,text in adapt_extraoptions_environment(shard_sources).items():(staged_gen/name).write_text(text)
            continuations=[]
            for path in sorted(staged_gen.glob('shard_*.c')):
                text,records=normalize_continuations(path.read_text())
                text,register_sites=normalize_register_returns(text,references);path.write_text(text)
                continuations.extend(records)
                continuations.extend({'site':row['site'],'target':row['target']}for row in references
                                     if row['kind']=='register_push_game_continuation_ret'and row['site']in register_sites)
            required={row['site']for row in references if row['kind']in
                      ('push_game_continuation_ret','register_push_game_continuation_ret')}
            missing=required-{row['site']for row in continuations}
            if missing:raise ValueError('game continuations were not normalized: '+','.join(f'{site:08x}'for site in sorted(missing)))
            entry=asdict(module)
            entry['continuations']=[dict(site=site,target=target)for site,target in
                                    sorted({(record['site'],record['target'])for record in continuations})]
            entry['entrypoints']=len(entries)
            entry['game_references']=references
            entry['functions']=len(re.findall(r'void sub_[0-9a-f]+\(',(staged_gen/'decls.h').read_text()))
            entry['unsupported_count']=sum(len(re.findall(r'unsupported_insn\(',p.read_text()))for p in staged_gen.glob('shard_*.c'))
            raw_manifest=staged_gen/'generation-manifest.json'
            provenance=json.loads(raw_manifest.read_text())
            # The base manifest describes raw C; bind our transformed outputs separately.
            raw_manifest.unlink()
            if (processor_hashes()!=processors or hashlib.sha256(source.read_bytes()).hexdigest()!=module.sha256):
                raise ValueError('module preparation inputs changed before publication')
            prepared={'key':module.key,'sha256':module.sha256,'module':asdict(module),
                      'raw_generation':provenance,
                      'processors':processors,
                      'artifacts':{path.name:hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sorted(staged_gen.iterdir())if path.is_file()}}
            (staged_out/MARKER).write_text(json.dumps({'key':module.key,'sha256':module.sha256})+'\n')
            (staged_gen/MARKER).write_text(json.dumps(prepared,indent=2)+'\n')
            # Both paths are generated caches. Move only directories bearing our marker.
            replace_generated(staged_out,out_root/module.key,module.key)
            replace_generated(staged_gen,gen_root/module.key,module.key)
            result['modules'].append(entry)
    result['game_entrypoints']=sorted({row['target']for module in result['modules']for row in module['game_references']})
    catalog.write_text(render_c_catalog(modules))
    (out_root/'modules.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game',type=Path)
    parser.add_argument('--out',type=Path,default=Path('out/hq-modules'))
    parser.add_argument('--generated',type=Path,default=Path('gen/hq'))
    parser.add_argument('--module',action='append',choices=[m.key for m in MODULES])
    args=parser.parse_args();modules=[m for m in MODULES if not args.module or m.key in args.module]
    result=prepare_modules(args.game,args.out,args.generated,modules)
    print('Prepared '+', '.join(m['key']for m in result['modules'])+'; Full runtime adapters still required.')


if __name__=='__main__':main()
