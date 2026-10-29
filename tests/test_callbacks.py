import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from tools.lift_callbacks import callback, emit, arena_callbacks


def code_at(base):
    return bytes.fromhex('8b44240450e8')+struct.pack('<i',0x401234-(base+10))+bytes.fromhex('83c404c3')


class CallbackTests(unittest.TestCase):
    def test_arena_capture_requires_the_audio_entry_call(self):
        base=0x5f800000
        def audio(entry,target):
            return bytes.fromhex('568b74240856e8')+struct.pack('<i',target-(entry+11))+bytes.fromhex('83c4045ec3')
        data=bytearray(256)
        data[16:32]=audio(base+16,0x8196c2)
        data[80:96]=audio(base+80,0x401000)
        data[144:160]=audio(base+144,0x8196c2)
        records=list(arena_callbacks(bytes(data),base))
        self.assertEqual([r['base'] for r in records],[base+16,base+144])
        self.assertEqual(records[0]['key'],records[1]['key'])

    def test_rebased_calls_share_a_template(self):
        a=callback(code_at(0x1000),0x1000)
        b=callback(code_at(0x2000),0x2000)
        self.assertEqual(a['key'],b['key'])
        self.assertNotEqual(a['bytes'],b['bytes'])

    def test_unbounded_or_branching_code_is_refused(self):
        for data in (b'\x90'*65536,bytes.fromhex('ebfec3'),bytes.fromhex('7505c3'),bytes.fromhex('7501b800000000c3'),
                     bytes.fromhex('e2fec3'),bytes.fromhex('e1fec3'),bytes.fromhex('e0fec3')):
            with self.assertRaises(ValueError):callback(data,0x1000)

    def test_bounded_forward_branch_compiles(self):
        data=bytes.fromhex('8b44240483f8057c05b805000000c3')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);emit([callback(data,0x1000)],root/'callbacks.c')
            (root/'test.c').write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];int native_generated_call(CPU *,uint32_t);
void dispatch_indirect(CPU *c,uint32_t fn){(void)c;(void)fn;abort();}
int main(void){g_mem=calloc(1,0x10000);g_cbits[0]=15;
unsigned char code[]={0x8b,0x44,0x24,4,0x83,0xf8,5,0x7c,5,0xb8,5,0,0,0,0xc3};
memcpy(g_mem+0x2000,code,sizeof code);CPU cpu={0},*c=&cpu;
for(unsigned n=2;n<9;n+=6){c->esp=0x5000;MR32(c->esp)=0xbeef;MR32(c->esp+4)=n;
assert(native_generated_call(c,0x2000));assert(c->eax==(n<5?n:5)&&c->eip==0xbeef&&c->esp==0x5004);}free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(root/'test.c'),str(root/'callbacks.c'),'-lm','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_matching_checks_middle_pages_and_keeps_short_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            emit([callback(b'\x90'*32768+b'\xc3',0x1000),callback(b'\xc3',0x1000)],root/'callbacks.c')
            (root/'test.c').write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];int native_generated_call(CPU *,uint32_t);
void dispatch_indirect(CPU *c,uint32_t fn){(void)c;(void)fn;abort();}
int main(void){g_mem=calloc(1,0x20000);g_cbits[0]=5;
memset(g_mem+0x1000,0x90,32768);MR8(0x9000)=0xc3;CPU cpu={0},*c=&cpu;c->esp=0x200;MR32(c->esp)=0xbeef;
assert(!native_generated_call(c,0x1000));MR8(0x3ff0)=0xc3;
assert(native_generated_call(c,0x3ff0)&&c->eip==0xbeef&&c->esp==0x204);free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(root/'test.c'),str(root/'callbacks.c'),'-lm','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

    def test_compiled_native_callback_matches_and_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            emit([callback(code_at(0x1000),0x1000)],root/'callbacks.c')
            harness=root/'test.c'
            harness.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem; uint8_t g_cbits[1u<<15];
int native_generated_call(CPU *,uint32_t);
void dispatch_indirect(CPU *c,uint32_t fn){assert(fn==0x401234);POP32(c->eip);c->eax=MR32(c->esp)*2;}
int main(void){g_mem=calloc(1,0x10000);g_cbits[0]=15;
unsigned char code[]={0x8b,0x44,0x24,0x04,0x50,0xe8,0x2a,0xf2,0x3f,0,0x83,0xc4,4,0xc3};
memcpy(g_mem+0x2000,code,sizeof code);CPU cpu={0},*c=&cpu;c->esp=0x5000;
MR32(c->esp)=0xbeef;MR32(c->esp+4)=21;
assert(native_generated_call(c,0x2000));assert(c->eax==42&&c->eip==0xbeef&&c->esp==0x5004);
MR8(0x2000)=0x90;assert(!native_generated_call(c,0x2000));free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(harness),str(root/'callbacks.c'),'-lm','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
