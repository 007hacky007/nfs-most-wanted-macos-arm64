from pathlib import Path
import hashlib
import struct
import subprocess
import tempfile
import unittest

from tools.lift import Lifter


def imported_call_image(name='ExitProcess',dll='KERNEL32.dll',prefix=b''):
    from tests.test_hq_module_catalog import fixture_dll
    raw=bytearray(fixture_dll());struct.pack_into('<I',raw,0x98+28,0x400000)
    struct.pack_into('<II',raw,0x98+104,0x3000,40)
    struct.pack_into('<II',raw,0x98+96+5*8,0,0)
    raw[0x400:0x600]=bytes(0x200)
    struct.pack_into('<IIIII',raw,0x400,0x3040,0,0,0x3060,0x3050)
    struct.pack_into('<II',raw,0x440,0x3080,0);struct.pack_into('<II',raw,0x450,0x3080,0)
    raw[0x460:0x460+len(dll)+1]=dll.encode()+b'\0'
    raw[0x480:0x480+len(name)+3]=b'\0\0'+name.encode()+b'\0'
    code=prefix+bytes.fromhex('ff1550304000b8efbeaddec3')
    raw[0x200:0x400]=b'\xcc'*0x200;raw[0x200:0x200+len(code)]=code
    return bytes(raw)


class LiftNoreturnTests(unittest.TestCase):
    def lifter(self,root,raw):
        path=root/'fixture.exe';path.write_bytes(raw);return Lifter(str(path))

    def test_only_proved_flat_exitprocess_calls_end_discovery(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp)
            for name,dll,prefix,expected in (
                    ('ExitProcess','KERNEL32.dll',b'',True),
                    ('ExitProcess','KERNEL32.dll',b'\x3e',True),
                    ('ExitProcess','KERNEL32.dll',b'\x64',False),
                    ('ExitProcess','KERNEL32.dll',b'\x65',False),
                    ('TerminateProcess','KERNEL32.dll',b'',False),
                    ('ExitProcess','OTHER.dll',b'',False)):
                with self.subTest(name=name,dll=dll,prefix=prefix):
                    lifter=self.lifter(root,imported_call_image(name,dll,prefix))
                    self.assertTrue(callable(getattr(lifter,'is_noreturn_call',None)))
                    blocks,_=lifter.discover(0x401000);instructions=blocks[0x401000]
                    self.assertEqual(lifter.is_noreturn_call(instructions[0]),expected)
                    self.assertEqual(instructions[-1].mnemonic,'call'if expected else'ret')
                    code,_=lifter.lift(0x401000)
                    self.assertEqual('__builtin_trap();'in code,expected)
                    self.assertEqual('0xdeadbeefu'in code,not expected)
                    self.assertEqual(lifter.traps,0)

    def test_unexpected_import_return_hits_assertion_without_running_fallthrough(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);lifter=self.lifter(root,imported_call_image());code,_=lifter.lift(0x401000)
            self.assertIn('__builtin_trap();',code)
            source=root/'check.c';source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
#include <setjmp.h>
uint8_t *g_mem;guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];static jmp_buf jump;static int return_import,called;
#define __builtin_trap() longjmp(jump,2)
void dispatch_indirect(CPU*c,uint32_t target){assert(target==0xf0000000u);called++;if(!return_import)longjmp(jump,1);POP32(c->eip);c->esp+=4;}
'''+code+'''
int main(void){g_mem=calloc(1,0x500000);assert(g_mem);MR32(0x403050)=0xf0000000;
for(return_import=0;return_import<2;return_import++){CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=17;int result=setjmp(jump);if(!result){sub_00401000(c);assert(0);}assert(result==(return_import?2:1)&&c->eax==17);}
assert(called==2);free(g_mem);return 0;}
''')
            binary=root/'check';build=subprocess.run(['clang','-O1','-Iruntime',str(source),'-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_actual_mw_exit_chain_and_mutation_reject_padding_fallthrough(self):
        candidates=(Path('out/installed/.nfsmw/runtime.exe'),Path('game/.nfsmw/runtime.exe'),Path('game/speed.exe'))
        image=next((path for path in candidates if path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()=='80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'),None)
        if image is None:self.skipTest('requires canonical 807 runtime')
        lifter=Lifter(str(image));self.assertEqual(getattr(lifter,'noreturn_functions',set()),{0x7ca340,0x7ca4d0})
        self.assertNotIn(0x7ca3a0,lifter.noreturn_functions)
        blocks,_=lifter.discover(0x666590)
        self.assertEqual({block[-1].mnemonic for block in blocks.values()}-{'call','jmp','je','jne','jp','jnp'},set())
        self.assertTrue(any(block[-1].address==0x66657c for block in blocks.values()))
        code,_=lifter.lift(0x666590);self.assertNotIn('00666582',code);self.assertEqual(lifter.traps,0)
        import pefile
        for address in (0x7ca340,0x7ca3a0,0x7ca4d0):
            with tempfile.TemporaryDirectory()as tmp:
                pe=pefile.PE(str(image));pe.set_bytes_at_rva(address-0x400000,b'\x90');changed=Path(tmp)/'changed.exe';pe.write(str(changed))
                changed_lifter=Lifter(str(changed));self.assertEqual(changed_lifter.noreturn_functions,set())
                changed_blocks,_=changed_lifter.discover(0x666590)
                self.assertTrue(any(block[-1].address==0x666582 for block in changed_blocks.values()))


if __name__=='__main__':unittest.main()
