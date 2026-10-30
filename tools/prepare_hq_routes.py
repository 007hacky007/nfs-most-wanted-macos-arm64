"""Compile captured .text variants and preserve original native function bodies."""
import argparse
from bisect import bisect_left
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import shutil
import tempfile
import struct
import pefile
try:
    from .lift import Lifter, parse_branch_hooks
    from .hq_routes import emit_wrappers, emit_native_names
    from .prepare_hq_modules import checked_output
    from .generation_manifest import verify_generation
    from .game_code_data import CANONICAL_SHA
    from .target import recover_relocations
except ImportError:
    from lift import Lifter, parse_branch_hooks
    from hq_routes import emit_wrappers, emit_native_names
    from prepare_hq_modules import checked_output
    from generation_manifest import verify_generation
    from game_code_data import CANONICAL_SHA
    from target import recover_relocations

ROOT=Path(__file__).resolve().parents[1]
MARKER='.hq-routes.json'


def processor_hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in (
        'tools/prepare_hq_routes.py','tools/hq_routes.py','tools/prepare_hq_modules.py',
        'tools/game_code_data.py','tools/target.py')}


def data_callback_targets(images,base,relocations,functions,start,size):
    """Recover replacement callbacks in proved data pointers, not instruction operands."""
    targets=set()
    for slot in relocations:
        if start<=slot<start+size:continue
        offset=slot-base
        before=struct.unpack_from('<I',images[0],offset)[0]
        if before not in functions:continue
        for image in images[1:]:
            target=struct.unpack_from('<I',image,offset)[0]
            if start<=target<start+size and target not in functions:targets.add(target)
    return targets


def verify_routes(output,generated,hook_file,branch_file):
    output,generated=Path(output),Path(generated)
    if output.is_symlink()or(output/MARKER).is_symlink():raise ValueError('route output symlink is unsupported')
    raw=(output/'manifest.json').read_bytes();record=json.loads(raw)
    marker=json.loads((output/MARKER).read_text())
    if marker.get('manifest_sha256')!=hashlib.sha256(raw).hexdigest():
        raise ValueError('route manifest differs')
    if record.get('processors')!=processor_hashes():raise ValueError('stale route processors; prepare routes again')
    if record.get('baseline_sha256')!=hashlib.sha256((generated/'generation-manifest.json').read_bytes()).hexdigest():
        raise ValueError('route baseline differs')
    verify_baseline(generated,output/'image0.exe',hook_file,branch_file)
    required={'decls.h','variants.c','routes.c','native_names.c','register.c','seeds.txt',
              *record['replaced_shards'],*(f'image{phase}.exe'for phase in range(len(record['phases'])))}
    if set(record['artifacts'])!=required:raise ValueError('route artifact inventory differs')
    for name,digest in record['artifacts'].items():
        if Path(name).name!=name:raise ValueError('invalid route artifact name')
        path=output/name
        if path.is_symlink()or not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError(f'route artifact differs: {name}')
    return record



def ranges_of(values):
    output=[]
    for value in sorted(set(values)):
        if output and output[-1][0]+output[-1][1]==value:output[-1][1]+=1
        else:output.append([value,1])
    return output


def checked_discovery(lifter,entry,phase=''):
    blocks,calls=lifter.discover(entry)
    for instructions in blocks.values():
        if not instructions:
            raise ValueError(f'game continuation {entry:08x} ({phase}) has no decoded instruction')
        last=instructions[-1].mnemonic
        if not (last.startswith('j')or last.startswith('loop')or last in ('ret','retf','hlt','ud2')or
                lifter.is_noreturn_call(instructions[-1])):
            raise ValueError(f'native function {entry:08x} ({phase}) has an undecodable or out-of-code fallthrough after {instructions[-1].address:08x} {last}')
    return blocks,calls


def verify_baseline(generated,exe,hooks,branches):
    record=verify_generation(generated,exe,hooks,branches)
    profile=record['options']
    unsupported=('WATCH','COVERAGE','JTSWITCH','LREGS','X87OPT','FTOL2INL','NOCLOSURE')
    if (any(profile[name]for name in unsupported)or not profile['X87PC']or
            not profile['FLAGOPT']or not profile['RETEIP']or profile['INLINE']or
            profile['CODE_RVA_START']is not None or profile['OVERRIDE']or profile['SYMPFX']or
            set(record['auxiliary'])!={'RELOCS'}):
        raise ValueError('unsupported baseline generation options for guarded native routing')
    # These legacy lifter switches are process-wide. Reject conflicting callers.
    module=sys.modules[Lifter.__module__]
    if (any(os.environ.get(name)=='1'for name in ('JTSWITCH','LREGS','X87OPT'))or
            any(os.environ.get(name)=='0'for name in ('FLAGOPT','RETEIP'))or
            os.environ.get('CODE_RVA_START')or module._FTOL2INL or module.abi_table()):
        raise ValueError('incompatible lifter environment for guarded native routing')
    return record


def generate(exe,generated,snapshots,output,extra_seeds=(),hook_file=None,branch_file=None,
             module_declarations=(),wrappers=(),patch_ranges=()):
    """Replace only managed generated output after the complete preparation succeeds."""
    exe,generated,output=Path(exe),Path(generated),Path(output)
    snapshots=[(name,Path(path))for name,path in snapshots]
    if output.is_symlink():raise ValueError('route output symlink is unsupported')
    output=checked_output(output)
    if output.is_relative_to(generated.resolve())or generated.resolve().is_relative_to(output):
        raise ValueError('route output overlaps baseline generated sources')
    inputs=[exe,*(path for _,path in snapshots),*(Path(path)for path in module_declarations)]
    if hook_file is None or branch_file is None:raise ValueError('explicit frozen hook and branch files are required')
    verify_baseline(generated,exe,hook_file,branch_file)
    inputs.extend([Path(hook_file),Path(branch_file)])
    input_hashes=[hashlib.sha256(path.read_bytes()).hexdigest()for path in inputs]
    processors=processor_hashes()
    if any(path.resolve().is_relative_to(output)for path in inputs):
        raise ValueError('route output overlaps input files')
    if output.exists():
        marker=output/MARKER
        if marker.is_symlink()or not marker.is_file()or json.loads(marker.read_text()).get('producer')!='hq-routes':
            raise ValueError('refusing to replace unmanaged route output')
    if len({name for name,_ in snapshots})!=len(snapshots)or any(name=='standard'for name,_ in snapshots):
        raise ValueError('duplicate or reserved phase name')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.routes-',dir=output.parent)as temporary:
        staged=Path(temporary)/'generated'
        result=_generate(exe,generated,snapshots,staged,extra_seeds,hook_file,branch_file,
                         module_declarations,wrappers,patch_ranges)
        if result['traps']:raise ValueError('captured variants contain unsupported or truncated instructions')
        if processors!=processor_hashes()or input_hashes!=[hashlib.sha256(path.read_bytes()).hexdigest()for path in inputs]:
            raise ValueError('route inputs or processors changed during preparation')
        verify_baseline(generated,exe,hook_file,branch_file)
        (staged/MARKER).write_text(json.dumps({'producer':'hq-routes','exe_sha256':result['exe_sha256'],
            'manifest_sha256':hashlib.sha256((staged/'manifest.json').read_bytes()).hexdigest()})+'\n')
        if output.exists():shutil.rmtree(output)
        shutil.move(str(staged),str(output))
    return result


def _generate(exe, generated, snapshots, output, extra_seeds=(), hook_file=None, branch_file=None, module_declarations=(), wrappers=(),patch_ranges=()):
    output.mkdir(parents=True,exist_ok=True)
    pe=pefile.PE(str(exe));base=pe.OPTIONAL_HEADER.ImageBase
    original=pe.get_memory_mapped_image();text=next(section for section in pe.sections if section.Name.rstrip(b'\0')==b'.text')
    start=base+text.VirtualAddress;size=text.Misc_VirtualSize;begin=start-base
    images=[original];names=['standard'];changes=set()
    for name,path in snapshots:
        if not re.fullmatch('[a-z][a-z0-9_]*',name):raise ValueError('invalid phase name')
        image=path.read_bytes()
        if len(image)!=pe.OPTIONAL_HEADER.SizeOfImage:raise ValueError('snapshot must contain the complete mapped game image')
        images.append(image);names.append(name)
        changes.update(start+i for i,(a,b) in enumerate(zip(original[begin:begin+size],image[begin:begin+size])) if a!=b)
    observed_changed_bytes=len(changes);patch_ranges=[list(row)for row in patch_ranges]
    for row in patch_ranges:
        if (len(row)!=2 or any(type(value)is not int for value in row)or row[1]<=0 or
                row[0]<start or row[0]+row[1]>start+size):
            raise ValueError('declared patch range is outside executable .text')
        changes.update(range(row[0],row[0]+row[1]))
    changed=sorted(changes)
    if hook_file is None or branch_file is None:raise ValueError('explicit frozen hook and branch files are required')
    hook_text=Path(hook_file).read_text().strip();branch_text=Path(branch_file).read_text().strip()
    hooks=[int(x,16)for x in hook_text.split(',')if x]
    branches=parse_branch_hooks(branch_text)
    lifters=[]
    for phase,image in enumerate(images):
        data=bytearray(exe.read_bytes())
        # Only captured text is used. Runtime IAT/data writes stay out of the generated PE.
        data[text.PointerToRawData:text.PointerToRawData+text.SizeOfRawData]=image[begin:begin+text.SizeOfRawData]
        path=output/f'image{phase}.exe';path.write_bytes(data)
        lifters.append(Lifter(str(path),trap=True,hooks=hooks,branch_hooks=branches,x87pc=True))
    function_table=(generated/'fntab.c').read_text().split('const uint32_t g_fn_addr[] = {',1)[1].split('};',1)[0]
    functions={int(x,16)for x in re.findall(r'0x([0-9a-f]+)u',function_table)}
    cache=output/'coverage.json';cache_key=hashlib.sha256(original+(generated/'fntab.c').read_bytes()+hook_text.encode()+branch_text.encode()).hexdigest()
    coverage=json.loads(cache.read_text())if cache.exists()else{}
    if coverage.get('key')!=cache_key:
        rows={}
        for entry in sorted(functions):
            blocks,_=lifters[0].discover(entry)
            rows[f'{entry:08x}']=ranges_of(a for block in blocks.values()for ins in block for a in range(ins.address,ins.address+ins.size))
        coverage={'key':cache_key,'functions':rows};cache.write_text(json.dumps(coverage,separators=(',',':'))+'\n')
    def overlaps(ranges):
        for address,length in ranges:
            i=bisect_left(changed,address)
            if i<len(changed)and changed[i]<address+length:return True
        return False
    affected={int(entry,16)for entry,ranges in coverage['functions'].items()if overlaps(ranges)}
    # A new CFG may reach bytes which the original function did not cover.
    # Adding every direct branch/call destination in captured edits makes these explicit entries.
    extra={int(x,16)if isinstance(x,str)else x for x in extra_seeds}-functions
    # ASI writers also replace vtable slots. Following only changed .text
    # misses those callbacks, including the Full HQ video-options handler.
    callbacks=data_callback_targets(images,base,recover_relocations(pe),functions,start,size) \
        if hashlib.sha256(exe.read_bytes()).hexdigest()==CANONICAL_SHA else set()
    extra.update(callbacks)
    if any(not start<=entry<start+size for entry in extra):
        raise ValueError('game continuation is outside executable .text')
    pending=set(extra);extra_code={};references=set();traps=[]
    for entry in affected:
        for phase,lifter in enumerate(lifters):
            _,refs=checked_discovery(lifter,entry,names[phase])
            references.update(refs)
            pending.update(ref for ref in refs if start<=ref<start+size and ref not in functions)
    pending=sorted(pending)
    while pending:
        entry=pending.pop()
        if entry in extra_code:continue
        for phase,lifter in enumerate(lifters):
            checked_discovery(lifter,entry,names[phase])
        refs=set()
        for phase,lifter in enumerate(lifters):
            lifter.traps=0
            code,phase_refs=lifter.lift(entry);refs.update(phase_refs)
            if phase==0:extra_code[entry]=code
            if lifter.traps or lifter.truncated:
                traps.append({'entry':entry,'phase':phase,'traps':lifter.traps,'truncated':lifter.truncated})
        references.update(refs)
        for ref in refs:
            if start<=ref<start+size and ref not in functions and ref not in extra_code:pending.append(ref)
    affected.update(extra_code)
    records=[];bodies=[]
    for entry in sorted(affected):
        coverage_bytes=set()
        for phase,lifter in enumerate(lifters):
            blocks,_=checked_discovery(lifter,entry,names[phase])
            for block in blocks.values():
                for ins in block:
                    if overlaps([[ins.address,ins.size]]):coverage_bytes.update(range(ins.address,ins.address+ins.size))
        ranges=ranges_of(coverage_bytes)
        if not ranges:
            if entry in extra_code:continue
            raise ValueError('affected function has no changed instruction')
        variants=[];seen=set()
        for phase,(image,lifter)in enumerate(zip(images,lifters)):
            signature=b''.join(image[address-base:address-base+length]for address,length in ranges)
            if signature in seen:continue
            seen.add(signature);symbol=f'sub_{entry:08x}_'+('standard'if phase==0 else f'full{phase}')
            variants.append({'symbol':symbol,'bytes':signature.hex(),'phase':names[phase]})
            if phase==0 and entry in functions:continue
            lifter.traps=0
            code,refs=lifter.lift(entry);references.update(refs)
            code=code.replace(f'void sub_{entry:08x}(',f'void {symbol}(',1)
            bodies.append(code)
            if lifter.traps or lifter.truncated:traps.append({'entry':entry,'phase':phase,'traps':lifter.traps,'truncated':lifter.truncated})
        records.append({'entry':entry,'ranges':ranges,'variants':variants})
    routed={row['entry']for row in records}
    for entry,code in extra_code.items():
        if entry not in routed:bodies.append(code)
    declarations=(generated/'decls.h').read_text()+'\n'
    declarations+='\n'.join(Path(path).read_text()for path in module_declarations)
    declarations+='\n'.join(f'void sub_{entry:08x}(CPU*);'for entry in sorted(references|set(extra_code)))+'\n'
    (output/'decls.h').write_text(declarations)
    (output/'variants.c').write_text('#include "cpu.h"\n#include "decls.h"\n#include <math.h>\n'+'\n'.join(bodies)+'\n')
    emit_wrappers(records,output/'routes.c')
    emit_native_names(records,set(extra_code),output/'native_names.c',wrappers)
    replaced=[]
    for path in sorted(generated.glob('shard_*.c')):
        source=path.read_text();count=0
        for entry in routed&functions:
            old=f'void sub_{entry:08x}(';new=f'void sub_{entry:08x}_standard('
            if old in source:source=source.replace(old,new,1);count+=1
        if count:(output/path.name).write_text(source);replaced.append(path.name)
    seeds=sorted(set(extra_code))
    (output/'seeds.txt').write_text(''.join(f'{entry:08x}\n'for entry in seeds))
    (output/'register.c').write_text('#include "cpu.h"\n#include "decls.h"\nvoid dispatch_patch(uint32_t,void(*)(CPU*));\nvoid hq_game_register(void){\n'+''.join(f' dispatch_patch(0x{entry:08x}u,sub_{entry:08x});\n'for entry in seeds)+'}\n')
    result={'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'phases':names,'changed_bytes':observed_changed_bytes,
            'data_callbacks':sorted(callbacks),
            'declared_patch_ranges':patch_ranges,'guarded_bytes':len(changes),
            'functions':records,'replaced_shards':replaced,'extra_entries':seeds,'traps':traps,
            'native_branches':[{'source':source,'target':target}for source,target in sorted(branches.items())],
            'hook_sites':hooks,'hook_input_sha256':hashlib.sha256(hook_text.encode()).hexdigest(),
            'branch_input_sha256':hashlib.sha256(branch_text.encode()).hexdigest(),
            'guard_scope':'Entry-time selection over observed byte ranges only; later writes outside those ranges and mutations inside an already-running body require explicit continuation guards and another capture.'}
    result['processors']=processor_hashes()
    result['baseline_sha256']=hashlib.sha256((generated/'generation-manifest.json').read_bytes()).hexdigest()
    result['artifacts']={path.name:hashlib.sha256(path.read_bytes()).hexdigest()for path in sorted(output.iterdir())
                         if path.suffix in ('.c','.h','.exe')or path.name=='seeds.txt'}
    (output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--gen',type=Path,required=True)
    parser.add_argument('--snapshot',action='append',required=True,metavar='NAME=PATH')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--seeds',type=Path)
    parser.add_argument('--hooks',type=Path,required=True)
    parser.add_argument('--branches',type=Path,required=True)
    parser.add_argument('--module-declarations',type=Path,action='append',default=[])
    parser.add_argument('--patch-ranges',type=Path,help='JSON address/length inventory for later code writers')
    args=parser.parse_args();os.environ['X87PC']='1'
    snapshots=[(name,Path(path))for name,path in (value.split('=',1)for value in args.snapshot)]
    result=generate(args.exe,args.gen,snapshots,args.out,args.seeds.read_text().split()if args.seeds else [],
                    args.hooks,args.branches,args.module_declarations,
                    patch_ranges=json.loads(args.patch_ranges.read_text())if args.patch_ranges else [])
    print(f"Prepared {len(result['functions'])} guarded native functions; {len(result['extra_entries'])} continuations.")


if __name__=='__main__':main()
