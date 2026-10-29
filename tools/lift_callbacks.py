#!/usr/bin/env python3
"""Build native templates for captured, bounded generated guest callbacks."""
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs,CS_ARCH_X86,CS_MODE_32,CS_GRP_JUMP
from capstone.x86 import X86_OP_IMM
try:
    from .lift import RawLifter
except ImportError:
    from lift import RawLifter


def callback(data,base):
    md=Cs(CS_ARCH_X86,CS_MODE_32);md.detail=True
    calls=[];branches=[];starts=set();length=0
    for insn in md.disasm(data[:65536],base):
        if insn.address!=base+length:raise ValueError('non-contiguous callback')
        starts.add(insn.address)
        length+=insn.size
        if CS_GRP_JUMP in insn.groups or insn.mnemonic in ('loop','loope','loopne'):
            if insn.operands[0].type!=X86_OP_IMM or insn.operands[0].imm<=insn.address:
                raise ValueError('backward or indirect callback branch needs separate analysis')
            branches.append(insn.operands[0].imm)
        if insn.mnemonic=='call':
            if insn.operands[0].type!=X86_OP_IMM or insn.imm_size!=4:
                raise ValueError('indirect callback call needs separate analysis')
            calls.append((insn.address-base,insn.size,insn.imm_offset,insn.operands[0].imm&0xffffffff))
        if insn.mnemonic=='ret':break
    else:raise ValueError('callback has no bounded return')
    if any(target not in starts for target in branches):
        raise ValueError('callback branch must target an instruction within the bounded body')
    data=bytes(data[:length]);mask=bytearray(b'\xff'*length)
    for offset,size,imm,target in calls:
        if base<=target<base+length:raise ValueError('internal callback call needs separate analysis')
        mask[offset+imm:offset+imm+4]=bytes(4)
    normalized=bytes(a&b for a,b in zip(data,mask))
    return {'key':hashlib.sha256(normalized+mask).hexdigest()[:20],
            'base':base,'bytes':data.hex(),'mask':mask.hex(),'calls':calls}


def arena_callbacks(data,base):
    prefix=bytes.fromhex('568b74240856e8')
    offset=0
    while (offset:=data.find(prefix,offset))>=0:
        entry=base+offset
        if offset+11<=len(data) and (entry+11+struct.unpack_from('<i',data,offset+7)[0])&0xffffffff==0x8196c2:
            try:yield callback(data[offset:offset+65536],entry)
            except ValueError:pass
        offset+=len(prefix)


def emit(records,output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    parts=['/* Generated native callback templates. Original bytes stay local. */',
           '#include "cpu.h"','#include <stdint.h>']
    for record in records:
        data=bytes.fromhex(record['bytes']);base=record['base'];key=record['key']
        lifter=RawLifter(data,base=base,comments=False)
        code,_=lifter.lift(base)
        code=code.replace(f'void sub_{base:08x}(CPU *restrict c) {{',
                          f'static void callback_{key}(CPU *restrict c,uint32_t entry) {{')
        for offset,size,imm,target in record['calls']:
            ret=base+offset+size
            old=f'PUSH32(0x{ret:x}u); dispatch_indirect(c, 0x{target:x}u);'
            new=(f'PUSH32(entry+0x{offset+size:x}u); '
                 f'dispatch_indirect(c,entry+0x{offset+size:x}u+(uint32_t)(int32_t)MR32(entry+0x{offset+imm:x}u));')
            if old not in code:raise ValueError('unexpected lifted callback call form')
            code=code.replace(old,new)
        parts.append(code)
        parts.append(f'static const uint8_t bytes_{key}[]={{'+','.join(str(x) for x in data)+'};')
        parts.append(f'static const uint8_t mask_{key}[]={{'+','.join(str(x) for x in bytes.fromhex(record['mask']))+'};')
    parts.append('int native_generated_call(CPU *c,uint32_t entry){')
    for record in records:
        key=record['key'];length=len(bytes.fromhex(record['bytes']))
        parts.append(f'if(entry<=UINT32_MAX-{length}u){{')
        parts.append(f'unsigned page=entry>>14,last=(entry+{length-1}u)>>14;')
        parts.append('for(;page<=last&&mem_is_committed(page<<14);page++);')
        parts.append('if(page>last){')
        parts.append(f'unsigned i;for(i=0;i<{length}u;i++)if(((MR8(entry+i)^bytes_{key}[i])&mask_{key}[i])!=0)break;')
        parts.append(f'if(i=={length}u){{callback_{key}(c,entry);return 1;}}'+'}}')
    parts.append('return 0;}')
    text='\n'.join(parts)+'\n'
    if not output.exists() or output.read_text()!=text:output.write_text(text)


def main():
    root=Path('out/callbacks');root.mkdir(parents=True,exist_ok=True)
    import sys
    if '--capture' in sys.argv:
        data=Path('out/missing-code.bin').read_bytes()
        base=int(Path('out/missing-code-address.txt').read_text(),16)
        record=callback(data,base)
        path=root/(record['key']+'.json')
        if path.exists():raise SystemExit('known callback template failed to match; investigate before adding more')
        path.write_text(json.dumps(record,indent=2)+'\n')
        print('Captured native callback template',record['key'],len(bytes.fromhex(record['bytes'])),'bytes')
    if '--arena' in sys.argv:
        arena=Path('out/missing-code-arena.bin')
        address=Path('out/missing-code-arena-address.txt')
        if not arena.exists():
            arena=Path('out/missing-code.bin');address=Path('out/missing-code-address.txt')
        added=0
        for record in arena_callbacks(arena.read_bytes(),int(address.read_text(),16)):
            path=root/(record['key']+'.json')
            if not path.exists():path.write_text(json.dumps(record,indent=2)+'\n');added+=1
        print('Additional bounded audio templates:',added)
    records=[json.loads(p.read_text()) for p in sorted(root.glob('*.json'))]
    emit(records,'gen/dynamic/callbacks.c')
    print('Native callback templates:',len(records))


if __name__=='__main__':main()
