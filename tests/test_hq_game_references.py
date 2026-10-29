import struct
import unittest
from pathlib import Path
import subprocess
import tempfile

from tools.hq_game_references import collect_game_references,normalize_register_returns
from tools.lift import RawLifter

BASE=0x01801000
TARGET=0x00668370


class HQGameReferenceTests(unittest.TestCase):
    def references(self,code):
        return collect_game_references(RawLifter(code,base=BASE),[BASE])

    def test_constant_register_copy_and_prefixed_call(self):
        code=b'\xb9'+struct.pack('<I',TARGET)+bytes.fromhex('89c83effd0c3')
        rows=self.references(code)
        self.assertEqual([(row['site'],row['target'],row['kind'])for row in rows],
                         [(BASE+7,TARGET,'constant_register_game_call')])

    def test_partial_writes_invalidate_only_the_correct_register_family(self):
        for mutation in (bytes.fromhex('b000'),bytes.fromhex('b400'),bytes.fromhex('6631c0')):
            code=b'\xb8'+struct.pack('<I',TARGET)+mutation+bytes.fromhex('ffd0c3')
            self.assertEqual(self.references(code),[])
        code=b'\xb8'+struct.pack('<I',TARGET)+bytes.fromhex('89c1b400ffd1c3')
        self.assertEqual(self.references(code)[0]['target'],TARGET)

    def test_calls_and_control_flow_boundaries_do_not_inherit_guesses(self):
        call=b'\xe8'+struct.pack('<i',0x1802000-(BASE+10))
        self.assertEqual(self.references(b'\xbe'+struct.pack('<I',TARGET)+call+bytes.fromhex('ffd6c3')),[])
        self.assertEqual(self.references(b'\xb8'+struct.pack('<I',TARGET)+bytes.fromhex('7400ffd0c3')),[])

    def test_direct_static_pointer_and_both_push_return_forms(self):
        relative=b'\xe9'+struct.pack('<i',TARGET-(BASE+5))
        self.assertEqual(self.references(relative)[0]['kind'],'direct_game_jmp')
        code=bytes.fromhex('ff15')+struct.pack('<I',BASE+0x20)+b'\xc3'
        rows=self.references(code.ljust(0x20,b'\xcc')+struct.pack('<I',TARGET))
        self.assertEqual((rows[0]['kind'],rows[0]['pointer'],rows[0]['target']),
                         ('static_game_call',BASE+0x20,TARGET))
        self.assertEqual(self.references(b'\x68'+struct.pack('<I',TARGET)+b'\xc3')[0]['kind'],
                         'push_game_continuation_ret')
        rows=self.references(b'\xb8'+struct.pack('<I',TARGET)+bytes.fromhex('50c3'))
        self.assertEqual((rows[0]['kind'],rows[0]['register'],rows[0]['site']),
                         ('register_push_game_continuation_ret','eax',BASE+5))

    def test_data_and_module_addresses_are_not_game_code(self):
        for target in (0x400000,0x900000,0x01801000,0xf0000000):
            self.assertEqual(self.references(b'\xb8'+struct.pack('<I',target)+bytes.fromhex('ffd0c3')),[])
        self.assertEqual(self.references(bytes.fromhex('ff1500000001c3')),[])

    def test_static_notrack_ds_is_flat_but_tls_segments_are_not(self):
        for prefix,expected in ((b'\x3e',True),(b'\x64',False),(b'\x65',False)):
            code=prefix+bytes.fromhex('ff15')+struct.pack('<I',BASE+0x20)+b'\xc3'
            rows=self.references(code.ljust(0x20,b'\xcc')+struct.pack('<I',TARGET))
            self.assertEqual(bool(rows),expected)
            if rows:self.assertEqual((rows[0]['site'],rows[0]['target']),(BASE,TARGET))

    def test_register_push_return_cave_keeps_the_original_native_return_frame(self):
        raw=b'\xb8'+struct.pack('<I',TARGET)+bytes.fromhex('50c3')
        lifter=RawLifter(raw,base=BASE);source,_=lifter.lift(BASE)
        source,changed=normalize_register_returns(source,collect_game_references(lifter,[BASE]))
        self.assertEqual(changed,{BASE+5})
        harness='''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;static unsigned calls;
void dispatch_indirect(CPU*c,uint32_t target){assert(target==0x668370&&c->esp==0x8000&&MR32(c->esp)==0xdeadbeef);calls++;POP32(c->eip);}
'''+source+'''
int main(void){g_mem=calloc(1,0x10000);CPU cpu={0},*c=&cpu;c->esp=0x8000;
MR32(c->esp)=0xdeadbeef;sub_01801000(c);
assert(calls==1&&c->eip==0xdeadbeef&&c->esp==0x8004);free(g_mem);return 0;}
'''
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);path=root/'cave.c';path.write_text(harness);binary=root/'cave'
            build=subprocess.run(['clang','-O1','-Iruntime',str(path),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
