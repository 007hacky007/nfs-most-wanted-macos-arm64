from pathlib import Path
import struct,subprocess,tempfile,unittest
from tools.lift import RawLifter
class RainDecodeTests(unittest.TestCase):
    def test_bnd_bytes_lengths_call_branch_and_return(self):
        raw=bytes.fromhex('f2e8')+struct.pack('<i',0x501000-0x401006)+bytes.fromhex('b82f000000f2c3')
        l=RawLifter(raw);code,_=l.lift(0x401000)
        instructions=list(l.md.disasm(raw,0x401000))
        self.assertEqual([(i.mnemonic,i.size)for i in instructions],[('call',6),('mov',5),('ret',2)])
        self.assertEqual(b''.join(i.bytes for i in instructions),raw)
        jump,_=RawLifter(bytes.fromhex('f27406b801000000c3b802000000f2c3'),base=0x402000).lift(0x402000)
        self.compile(code+'\n'+jump,r'''
CPU cpu={0},*c=&cpu;c->esp=0x8000;PUSH32(0xdeadbeef);sub_00401000(c);
assert(c->eax==47&&c->esp==0x8000&&c->eip==0xdeadbeef&&calls==1);
for(unsigned z=0;z<2;z++){c->zf=z;c->esp=0x8000;PUSH32(0xdeadbeef);sub_00402000(c);
 assert(c->eax==(z?2:1)&&c->esp==0x8000&&c->eip==0xdeadbeef);}
''')
    def test_bnd_jump_and_callee_cleanup(self):
        code,_=RawLifter(bytes.fromhex('f2e905000000b801000000f2c20800')).lift(0x401000)
        self.compile(code,r'''
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=123;c->cf=c->zf=1;
PUSH32(7);PUSH32(8);PUSH32(0xdeadbeef);sub_00401000(c);
assert(c->eax==123&&c->esp==0x8000&&c->eip==0xdeadbeef&&c->cf&&c->zf);
''')
    def test_unpcklpd_preserves_bits_aliases_and_memory_source(self):
        code,_=RawLifter(bytes.fromhex('660f14c0660f14c8660f1410c3')).lift(0x401000)
        self.compile(code,r'''
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=0x9000;c->xmm[0].u64[0]=0x7ff8000012345678ull;
c->xmm[0].u64[1]=0x1111111111111111ull;c->xmm[1].u64[0]=0x8000000000000000ull;
c->xmm[2].u64[0]=123;MR64(0x9000)=0xfff0000000000000ull;PUSH32(0xdeadbeef);sub_00401000(c);
assert(c->xmm[0].u64[0]==0x7ff8000012345678ull&&c->xmm[0].u64[1]==c->xmm[0].u64[0]);
assert(c->xmm[1].u64[0]==0x8000000000000000ull&&c->xmm[1].u64[1]==c->xmm[0].u64[0]);
assert(c->xmm[2].u64[0]==123&&c->xmm[2].u64[1]==0xfff0000000000000ull);
''')
    def compile(self,code,body):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.c'
            path.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;unsigned calls;guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
void dispatch_indirect(CPU*c,uint32_t target){assert(target==0x501000&&MR32(c->esp)==0x401006);calls++;POP32(c->eip);c->eax=9;}
'''+code+'\nint main(void){g_mem=calloc(1,0x10000);'+body+'free(g_mem);}')
            result=subprocess.run(['clang','-O1','-Iruntime',str(path),'-o',str(Path(tmp)/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(Path(tmp)/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
if __name__=='__main__':unittest.main()
