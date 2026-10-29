"""Verified switch data inside the canonical executable's code section."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_EAX, X86_REG_EDX

CANONICAL_SHA='80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'


@dataclass(frozen=True)
class Switch:
    owner: int
    boundary: int
    branch: int
    dispatch: int
    table: int
    targets: tuple
    index: int = 0
    index_count: int = 0
    tail_target: int = 0


SWITCHES=(
    Switch(0x601790,0x601f74,0x601d3f,0x601d45,0x601f78,
           (0x601d4c,0x601d60,0x601d74,0x601d88,0x601d9c,0x601db0)),
    Switch(0x6c68b0,0x6c6c9d,0x6c69da,0x6c69dc,0x6c6ca0,
           (0x6c69e3,0x6c69ef,0x6c6a13,0x6c6a1a,0x6c69fb,0x6c6a07)),
    Switch(0x6d6000,0x6d6420,0x6d6085,0x6d6092,0x6d6424,
           (0x6d6099,0x6d6165,0x6d6199,0x6d61cd,0x6d6131,0x6d60c9,0x6d6235,
            0x6d6269,0x6d60fd,0x6d629d,0x6d62d1,0x6d62fe,0x6d6201,0x6d632b),0x6d645c,31),
    Switch(0x6d7500,0x6d7622,0x6d7536,0x6d753f,0x6d7624,(0x6d7546,0x6d758d),0x6d762c,19),
    Switch(0x6d7500,0x6d7622,0x6d75b5,0x6d75be,0x6d7640,(0x6d75c5,0x6d75de),0x6d7648,19),
    Switch(0x6d7660,0x6d7929,0x6d76a2,0x6d76ab,0x6d792c,(0x6d76b2,0x6d76eb),0x6d7934,19),
    Switch(0x6e0770,0x6e0a2e,0x6e08b3,0x6e08c0,0x6e0a94,(0x6e08c7,0x6e09e2),0x6e0a9c,19),
    Switch(0x7a5ee0,0x7a5f23,0x7a5eed,0x7a5eef,0x7a5f28,
           (0x7a5ef6,0x7a5efe,0x7a5f06,0x7a5f0e,0x7a5f16,0x7a5f1e)),
    Switch(0x7b42b0,0x7b456a,0x7b44b8,0x7b44ba,0x7b4570,
           (0x7b44d6,0x7b44c1,0x7b44c8,0x7b44cf),tail_target=0x7aa4b0),
)


def register_bound(lifter,block):
    """The one verified switch whose limit is loaded into a register."""
    instructions={ins.address:ins for ins in block}
    required=(0x6c69cd,0x6c69d2,0x6c69d3,0x6c69d5,0x6c69da)
    if not all(address in instructions for address in required):return None
    load,decrement,compare,move,branch=(instructions[address] for address in required)
    if (load.mnemonic!='mov' or len(load.operands)!=2 or
            load.operands[0].type!=X86_OP_REG or load.operands[0].reg!=X86_REG_EAX or
            load.operands[1].type!=X86_OP_IMM or load.operands[1].imm!=5 or
            decrement.mnemonic!='dec' or decrement.operands[0].reg!=X86_REG_EDX or
            compare.mnemonic!='cmp' or len(compare.operands)!=2 or
            any(op.type!=X86_OP_REG for op in compare.operands) or
            (compare.operands[0].reg,compare.operands[1].reg)!=(X86_REG_EDX,X86_REG_EAX) or
            move.mnemonic!='mov' or lifter._jt_writes(move,'edx') or
            branch.mnemonic!='ja' or branch.operands[0].type!=X86_OP_IMM or
            branch.operands[0].imm!=0x6c6a1a):return None
    if any(a.address+a.size!=b.address for a,b in zip((load,decrement,compare,move),(decrement,compare,move,branch))):return None
    return X86_REG_EDX,5,branch.address+branch.size


def relocation_data_ranges(exe,lifter):
    """Exclude proven data only from relocation-derived function roots."""
    if hashlib.sha256(Path(exe).read_bytes()).hexdigest()!=CANONICAL_SHA:return ()
    ranges=[];owners={}
    error='canonical code data metadata does not match decoded switch structure'
    for switch in SWITCHES:
        if switch.owner not in owners:owners[switch.owner]=lifter.discover(switch.owner)[0]
        blocks=owners[switch.owner]
        instructions={ins.address:ins for block in blocks.values() for ins in block}
        endings={block[-1].address:block for block in blocks.values() if block}
        boundary=instructions.get(switch.boundary)
        if boundary is None:raise ValueError(error)
        if switch.tail_target:
            if (boundary.mnemonic!='jmp' or boundary.operands[0].type!=X86_OP_IMM or
                    boundary.operands[0].imm!=switch.tail_target):raise ValueError(error)
        elif boundary.mnemonic!='ret':raise ValueError(error)
        bounded=endings.get(switch.branch)
        if not bounded:raise ValueError(error)
        bound=lifter._jt_bound(bounded)
        if switch.branch==0x6c69da:bound=register_bound(lifter,bounded)
        count=switch.index_count if switch.index else len(switch.targets)
        if not bound or bound[1]!=count-1:raise ValueError(error)
        indirect=blocks.get(bound[2])
        if not indirect or indirect[-1].address!=switch.dispatch:raise ValueError(error)
        if switch.index:
            ins=indirect[0]
            if (ins.mnemonic!='movzx' or len(ins.operands)!=2 or
                    ins.operands[0].type!=X86_OP_REG or
                    ins.operands[1].type!=X86_OP_MEM or ins.operands[1].size!=1 or
                    ins.operands[1].mem.disp!=switch.index):raise ValueError(error)
        decoded=lifter._jt_table(indirect,bound[:2])
        if not decoded or decoded[1:]!=(switch.table,list(switch.targets)):raise ValueError(error)
        table_end=switch.table+4*len(switch.targets)
        if not switch.boundary<switch.table:raise ValueError(error)
        ranges.append((switch.table,table_end))
        if switch.index:
            if table_end!=switch.index:raise ValueError(error)
            ranges.append((switch.index,switch.index+switch.index_count))
    return tuple(ranges)
