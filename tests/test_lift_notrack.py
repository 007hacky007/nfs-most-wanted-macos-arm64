from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.lift import RawLifter


class NotrackDecodeTests(unittest.TestCase):
    def test_call_retains_bytes_length_ds_operand_and_return_address(self):
        raw=bytes.fromhex('3eff1500900000b82f000000c3')
        lifter=RawLifter(raw);code,_=lifter.lift(0x401000)
        instructions=list(lifter.md.disasm(raw,0x401000))
        self.assertEqual([(i.mnemonic,i.size)for i in instructions],[('call',7),('mov',5),('ret',1)])
        self.assertIn('ds:',instructions[0].op_str)
        self.assertEqual(b''.join(i.bytes for i in instructions),raw)
        self.assertEqual(lifter.traps,0)
        self.compile(code,'''MR32(0x9000)=0x501000;c->esp=0x8000;PUSH32(0xdeadbeef);sub_00401000(c);
assert(calls==1&&c->eax==47&&c->esp==0x8000&&c->eip==0xdeadbeef);''',0x401007)

    def test_tail_jump_preserves_original_return_frame_and_flags(self):
        raw=bytes.fromhex('3effe0')
        lifter=RawLifter(raw);code,_=lifter.lift(0x401000)
        instructions=list(lifter.md.disasm(raw,0x401000))
        self.assertEqual([(i.mnemonic,i.size)for i in instructions],[('jmp',3)])
        self.assertEqual(b''.join(i.bytes for i in instructions),raw)
        self.assertEqual(lifter.traps,0)
        self.compile(code,'''c->eax=0x501000;c->esp=0x8000;c->cf=c->zf=1;PUSH32(0xdeadbeef);sub_00401000(c);
assert(calls==1&&c->esp==0x8000&&c->eip==0xdeadbeef&&c->cf&&c->zf);''',0xdeadbeef)

    def compile(self,code,body,expected_return):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];static unsigned calls;
void dispatch_indirect(CPU*c,uint32_t target){assert(target==0x501000&&MR32(c->esp)=='''+hex(expected_return)+''');calls++;POP32(c->eip);}
'''+code+'\nint main(void){g_mem=calloc(1,0x10000);CPU cpu={0},*c=&cpu;'+body+'free(g_mem);}')
            result=subprocess.run(['clang','-O1','-Iruntime',str(source),'-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
