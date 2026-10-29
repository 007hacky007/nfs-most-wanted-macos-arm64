"""Recover provable game entrypoints referenced by a separately lifted module."""
import struct
import argparse
import json
from pathlib import Path
import re
from capstone.x86 import X86_OP_IMM,X86_OP_MEM,X86_OP_REG,X86_REG_FS,X86_REG_GS

GAME_TEXT=(0x00401000,0x0088f2a5)
ALIASES={name:group[0]for group in (
    ('eax','ax','al','ah'),('ebx','bx','bl','bh'),('ecx','cx','cl','ch'),('edx','dx','dl','dh'),
    ('esi','si'),('edi','di'),('ebp','bp'),('esp','sp'))for name in group}


def collect_game_references(lifter,functions,game_range=GAME_TEXT):
    """Track constants inside a block only; calls invalidate every register value."""
    rows={}
    def family(register):
        name=lifter.md.reg_name(register)
        return ALIASES.get(name,name)
    def read32(address):
        for _,base,_,data in lifter.secs:
            if base<=address<=base+len(data)-4:return struct.unpack_from('<I',data,address-base)[0]
        return None
    def record(function,site,target,kind,**details):
        if target is None or not game_range[0]<=target<game_range[1]:return
        row=dict(function=function,site=site,target=target,kind=kind,**details)
        rows.setdefault((site,target,kind),row)
    for function in sorted(set(functions)):
        blocks,_=lifter.discover(function)
        for instructions in blocks.values():
            known={};push=None
            for ins in instructions:
                operands=ins.operands;mnemonic=ins.mnemonic
                if mnemonic in ('call','jmp')and operands:
                    operand=operands[0]
                    if operand.type==X86_OP_IMM:
                        record(function,ins.address,operand.imm&0xffffffff,'direct_game_'+mnemonic)
                    elif operand.type==X86_OP_REG:
                        record(function,ins.address,known.get(family(operand.reg)),
                               'constant_register_game_'+mnemonic)
                    elif operand.type==X86_OP_MEM:
                        memory=operand.mem
                        if not(memory.base or memory.index)and memory.segment not in (X86_REG_FS,X86_REG_GS):
                            pointer=memory.disp&0xffffffff
                            record(function,ins.address,read32(pointer),'static_game_'+mnemonic,pointer=pointer)
                if mnemonic=='ret'and not operands and push:
                    record(function,**push)
                push=None
                if mnemonic=='push'and operands:
                    operand=operands[0]
                    if operand.type==X86_OP_IMM:
                        push=dict(site=ins.address,target=operand.imm&0xffffffff,kind='push_game_continuation_ret')
                    elif operand.type==X86_OP_REG:
                        push=dict(site=ins.address,target=known.get(family(operand.reg)),
                                  kind='register_push_game_continuation_ret',register=lifter.md.reg_name(operand.reg))
                value=None
                if mnemonic=='mov'and len(operands)==2 and operands[0].type==X86_OP_REG and operands[0].size==4:
                    if operands[1].type==X86_OP_IMM:value=operands[1].imm&0xffffffff
                    elif operands[1].type==X86_OP_REG and operands[1].size==4:value=known.get(family(operands[1].reg))
                for register in ins.regs_access()[1]:known.pop(family(register),None)
                if value is not None:known[family(operands[0].reg)]=value
                if mnemonic=='call':known.clear()
    return [rows[key]for key in sorted(rows)]


def normalize_register_returns(source,references):
    """Dispatch a proved register push/RET cave with its original caller frame."""
    changed=set()
    for row in references:
        if row['kind']!='register_push_game_continuation_ret':continue
        register=row['register']
        if register not in {group for group in ALIASES.values()}:
            raise ValueError('invalid continuation register')
        site=row['site']
        pattern=(r'(/\* '+f'{site:08x}'+r'\b[^\n]*\*/\s*)PUSH32\(c->'+register+
                 r'\);\s*/\* [0-9a-f]{8}\s+ret\s*\*/\s*POP32\(c->eip\); return;')
        source,count=re.subn(pattern,lambda match:match[1]+f'DISPATCH_TAIL(c, c->{register});',source)
        if count:changed.add(site)
    return source,changed


def main():
    try:
        from .lift import Lifter
    except ImportError:
        from lift import Lifter
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('declarations',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    functions=[int(value,16)for value in re.findall(r'void sub_([0-9a-f]+)\(',args.declarations.read_text())]
    rows=collect_game_references(Lifter(str(args.image)),functions)
    args.output.write_text(json.dumps(rows,indent=2)+'\n')
    print(f'Recovered {len(rows)} game references and {len({row["target"]for row in rows})} entrypoints.')


if __name__=='__main__':main()
