"""Represented control/status words for six pinned ExtraOptions CRT sites only.

These private helpers initialize a 28-byte frame and inspect only its control
and status slots. Tag/pointer fields are not represented or generalized here.
Call input validation before generation mutates output, then adapt the complete
source mapping before recording its final artifact hashes. Neither API writes.
"""
from collections.abc import Mapping
import hashlib
import re

EXTRAOPTIONS_SHA256='32bc3ae6c3f36218ae507b666d8fb816c2263fdb7819498286bca11537ec8ff2'
BASE=0x01c00000
HELPERS=((0x01c2dac7,0x01c2db47,0x01c2dadb,0x01c2dade),
         (0x01c2dbf1,0x01c2dc6c,0x01c2dc10,0x01c2dc2c),
         (0x01c2dc6c,0x01c2dd66,0x01c2dcda,0x01c2dceb))
SITES={site:(entry,opcode)for entry,_,store,load in HELPERS
       for site,opcode in ((store,'fnstenv'),(load,'fldenv'))}
STORE='MR32(c->ebp-0x20u)=c->fcw; MR32(c->ebp-0x1cu)=fsw_get(c); c->fcw|=0x3fu;'
LOAD='c->fcw=MR16(c->ebp-0x20u); c->fsw=MR16(c->ebp-0x1cu); c->top=(c->fsw>>11)&7u;'


def _validate_frame(instructions,entry,store,load):
    from capstone import CS_AC_WRITE
    from capstone.x86 import X86_OP_IMM,X86_OP_MEM,X86_OP_REG
    from capstone.x86 import X86_REG_EAX,X86_REG_EBP,X86_REG_ECX,X86_REG_EDI,X86_REG_ESP
    expected=(('mov','edi, edi'),('push','ebp'),('mov','ebp, esp'),('sub','esp, 0x20'))
    if tuple((i.mnemonic,i.op_str)for i in instructions[:4])!=expected:
        raise ValueError(f'private CRT frame differs at {entry:08x}')
    if [(i.mnemonic,i.op_str)for i in instructions[-2:]]!=[('leave',''),('ret','')]:
        raise ValueError(f'private CRT epilogue differs at {entry:08x}')
    state={X86_REG_EAX:None,X86_REG_ECX:None,X86_REG_EDI:None};stack=[];initialized=0;sites=set()
    for index,ins in enumerate(instructions):
        operands=ins.operands;opcode=ins.mnemonic
        if opcode in ('fnstenv','fldenv'):
            if (ins.address not in SITES or SITES[ins.address]!=(entry,opcode)or
                    len(operands)!=1 or operands[0].type!=X86_OP_MEM or
                    operands[0].size!=28 or operands[0].mem.base!=X86_REG_EBP or
                    operands[0].mem.index or operands[0].mem.segment or operands[0].mem.disp!=-32):
                raise ValueError(f'CRT environment operand differs at {ins.address:08x}')
            sites.add(ins.address)
        if store<ins.address<load and opcode=='call':
            raise ValueError('private environment frame escapes through a call')
        for operand in operands:
            if operand.type!=X86_OP_MEM:continue
            mem=operand.mem
            if mem.index:raise ValueError('indexed private environment access')
            if mem.base==X86_REG_EBP:
                if opcode in ('fnstenv','fldenv'):continue
                if opcode=='lea':
                    if (mem.disp!=-32 or operands[0].reg!=X86_REG_EDI or ins.address>=store):
                        raise ValueError('private environment address escapes')
                elif mem.disp>=8:
                    if operand.access&CS_AC_WRITE:raise ValueError('CRT argument write differs')
                elif (mem.disp,operand.size)not in ((-32,4),(-28,4),(-32,2),(-28,2),(-4,4)):
                    raise ValueError('unrepresented environment field accessed')
            elif mem.base==X86_REG_EDI and opcode=='rep stosd':
                pass
            elif mem.base:
                raise ValueError('unproved private environment memory alias')
        if opcode=='rep stosd':
            if (ins.address>=store or initialized or state[X86_REG_EAX]!=0 or
                    state[X86_REG_ECX]!=7 or state[X86_REG_EDI]!=('frame',-32)):
                raise ValueError('private environment initializer differs')
            initialized+=1
        before=dict(state)
        for register in ins.regs_access()[1]:
            if register in state:state[register]=None
            if register==X86_REG_EBP and index!=2 and opcode!='leave':
                raise ValueError('private CRT frame pointer changed')
        if opcode=='push':
            operand=operands[0]
            value=operand.imm if operand.type==X86_OP_IMM else before.get(operand.reg)if operand.type==X86_OP_REG else None
            if isinstance(value,tuple):raise ValueError('private environment pointer passed on stack')
            stack.append(value)
        elif opcode=='pop':
            value=stack.pop()if stack else None
            if operands[0].reg in state:state[operands[0].reg]=value
        elif opcode=='xor'and len(operands)==2 and operands[0].type==operands[1].type==X86_OP_REG and operands[0].reg==operands[1].reg:
            if operands[0].reg in state:state[operands[0].reg]=0
        elif opcode=='lea'and operands[0].reg==X86_REG_EDI:
            state[X86_REG_EDI]=('frame',-32)
        elif opcode=='mov'and operands[0].type==X86_OP_REG and operands[0].reg in state:
            source=operands[1];state[operands[0].reg]=source.imm if source.type==X86_OP_IMM else before.get(source.reg)if source.type==X86_OP_REG else None
        elif opcode=='call':
            state[X86_REG_EAX]=state[X86_REG_ECX]=None
    if initialized!=1 or sites!={store,load}:
        raise ValueError(f'incomplete private CRT environment at {entry:08x}')


def validate_extraoptions_environment(raw:bytes,guest_base:int=BASE)->None:
    """Validate the original pinned PE and the six decoded private-frame sites."""
    if hashlib.sha256(raw).hexdigest()!=EXTRAOPTIONS_SHA256:
        raise ValueError('unsupported ExtraOptions environment SHA-256')
    if guest_base!=BASE:raise ValueError('unsupported ExtraOptions environment guest base')
    import capstone
    import pefile
    pe=pefile.PE(data=raw,fast_load=True)
    if pe.FILE_HEADER.Machine!=0x14c or pe.OPTIONAL_HEADER.Magic!=0x10b or pe.OPTIONAL_HEADER.SizeOfImage!=0x48000:
        raise ValueError('ExtraOptions environment PE metadata differs')
    decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32);decoder.detail=True
    for entry,end,store,load in HELPERS:
        section=pe.get_section_by_rva(entry-BASE)
        if (section is None or not section.Characteristics&0x20000000 or
                end-BASE>section.VirtualAddress+section.Misc_VirtualSize):
            raise ValueError('CRT helper is outside executable input')
        code=pe.get_data(entry-BASE,end-entry);instructions=list(decoder.disasm(code,entry))
        if sum(ins.size for ins in instructions)!=end-entry:
            raise ValueError('incomplete CRT helper decoding')
        _validate_frame(instructions,entry,store,load)


def adapt_extraoptions_environment(sources:Mapping[str,str])->dict[str,str]:
    """Return source copies with exactly six validated traps replaced.

    Requires normal commented genall function bodies. A partial, duplicate,
    already adapted or misplaced site fails without mutating the input mapping.
    Other functions, instructions and traps are retained verbatim.
    """
    functions=re.compile(r'^void sub_([0-9a-f]{8})\(CPU \*(?:restrict )?c\) \{',re.M)
    traps=re.compile(r'unsupported_insn\(c,\s*0x([0-9a-f]+)u,\s*"(fnstenv|fldenv)"\);')
    found=set();replacements={};owners=set()
    for name,text in sources.items():
        if not isinstance(name,str)or not isinstance(text,str):raise ValueError('generated sources must be text mappings')
        spans=[]
        for function in functions.finditer(text):
            owner=int(function[1],16)
            if owner in {item[0]for item in HELPERS}:
                if owner in owners:raise ValueError('duplicate private CRT helper')
                owners.add(owner)
            end=text.find('\n}',function.end())
            if end<0:raise ValueError('incomplete generated function')
            spans.append((function.start(),end+2,int(function[1],16)))
        for trap in traps.finditer(text):
            site=int(trap[1],16)
            if site not in SITES:continue
            owner,opcode=SITES[site]
            if site in found:raise ValueError(f'duplicate CRT environment site {site:08x}')
            function=next((span for span in spans if span[0]<=trap.start()<span[1]),None)
            comment=rf'/\*\s*{site:08x}\s+{opcode} \[ebp - 0x20\]\s*\*/\s*$'
            if (function is None or function[2]!=owner or trap[2]!=opcode or
                    not re.search(comment,text[function[0]:trap.start()])):
                raise ValueError(f'CRT environment source context differs at {site:08x}')
            found.add(site);replacements.setdefault(name,[]).append((trap.start(),trap.end(),STORE if opcode=='fnstenv'else LOAD))
    if found!=set(SITES):raise ValueError('missing CRT environment sites')
    result=dict(sources)
    for name,items in replacements.items():
        for start,end,replacement in reversed(items):result[name]=result[name][:start]+replacement+result[name][end:]
    return result
