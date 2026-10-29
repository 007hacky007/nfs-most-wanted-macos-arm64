import os
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.lift import RawLifter, Unsupported, NativeBranchError, parse_branch_hooks


class BranchHookTests(unittest.TestCase):
    def test_branch_manifest_is_bounded_and_rejects_duplicates(self):
        self.assertEqual(parse_branch_hooks(''), {})
        self.assertEqual(parse_branch_hooks('00401000:0x401005'), {0x401000:0x401005})
        for text in ('00401000','1:2:3','-1:2','1:100000000','1:2,1:3'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_branch_hooks(text)

    def test_native_branch_splits_blocks_and_preserves_x87_and_live_flags(self):
        # The native edge skips an XOR whose original CFG made ADD's flags dead.
        data = bytes.fromhex('53d9e8d9e8dec1b8ffffffff83c00131c0d91d002000005bc3')
        site, target = 0x40100f, 0x401011
        with patch.dict(os.environ, {'X87OPT': '1', 'X87PC': '1'}):
            lifter = RawLifter(data, branch_hooks={site: target})
            code, _ = lifter.lift(0x401000)
        self.assertIn('if (guest_branch(c, 0x40100fu)) goto L_00401011;', code)
        harness = r'''
#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;static int take;
int guest_branch(CPU *c,uint32_t ip){
 assert(ip==0x40100f&&c->cf==1&&c->zf==1&&c->st[c->top&7]==2.0);return take;
}
''' + code + r'''
int main(void){
 g_mem=calloc(1,65536);assert(g_mem);
 for(take=0;take<2;take++){
  CPU cpu={0},*c=&cpu;c->esp=0x9000;c->ebx=123;c->fcw=0x027f;
  MR32(c->esp)=0xdeadbeef;sub_00401000(c);
  assert(c->esp==0x9004&&c->eip==0xdeadbeef&&c->ebx==123&&c->eax==0);
  assert(c->cf==(unsigned)take&&c->zf==1&&c->top==0&&MRF32(0x2000)==2.0f);
 }
 free(g_mem);return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.c'; source.write_text(harness)
            binary = Path(tmp) / 'test'
            result = subprocess.run(['clang', '-O1', '-Iruntime', str(source), '-lm', '-o', str(binary)],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_branch_target_must_be_an_existing_instruction_in_the_same_body(self):
        data = bytes.fromhex('b801000000c3')
        for target in (0x401001, 0x401100):
            with self.subTest(target=target), self.assertRaises(Unsupported):
                RawLifter(data, branch_hooks={0x401000: target}).lift(0x401000)
        lifter = RawLifter(data, branch_hooks={0x402000: 0x402005})
        code, _ = lifter.lift(0x401000)
        self.assertNotIn('guest_branch', code)

    def test_branch_and_observer_hooks_cannot_share_a_site(self):
        with self.assertRaises(ValueError):
            RawLifter(b'\xc3', hooks=[0x401000], branch_hooks={0x401000: 0x401000})

    def test_unsynchronized_register_local_optimization_is_rejected(self):
        with patch.dict(os.environ, {'LREGS': '1'}), self.assertRaises(NativeBranchError):
            RawLifter(b'\x90\xc3', branch_hooks={0x401000:0x401001}).lift(0x401000)

    def test_generation_aborts_instead_of_emitting_standard_trap_stubs(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv', ['genall.py','unused','1']), \
                patch.dict(os.environ, {'GENOUT':tmp,'LREGS':'0','BRANCH_HOOKS':''}):
            spec=importlib.util.spec_from_file_location('native_branch_generator','tools/genall.py')
            generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
            class InvalidTarget:
                def lift(self, address):
                    raise generator.NativeBranchError('invalid native branch target')
            generator._L=InvalidTarget()
            with self.assertRaises(generator.NativeBranchError):
                generator._shard((0,[0x401000]))
            with self.assertRaises(generator.NativeBranchError):
                generator._inlprobe(0x401000)
            self.assertFalse((Path(tmp)/'shard_0000.c').exists())


if __name__ == '__main__':
    unittest.main()
