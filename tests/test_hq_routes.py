from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest
import sys
from unittest.mock import patch

from tests.test_hq_module_catalog import fixture_dll
from tools.prepare_hq_routes import generate,verify_routes
from tools.lift import RawLifter
from tools.generation_manifest import record_generation


class HQRouteTests(unittest.TestCase):
    def record(self,exe,baseline,hooks,branches):
        relocs=exe.with_suffix('.relocs');relocs.write_text('')
        with patch.dict(os.environ,{'RELOCS':str(relocs),'X87PC':'1'}):
            record_generation(baseline,exe,hooks,branches)

    def fixture(self,root):
        import pefile
        data=bytearray(fixture_dll());struct.pack_into('<I',data,0x98+28,0x400000)
        data[0x200:0x400]=b'\xcc'*0x200
        for offset,code in [(0,bytes.fromhex('b801000000c3')),(0x20,b'\xc3'),
                            (0x40,b'\xc3'),(0x60,bytes.fromhex('b805000000c3'))]:
            data[0x200+offset:0x200+offset+len(code)]=code
        exe=root/'fixture.exe';exe.write_bytes(data)
        original=pefile.PE(data=data).get_memory_mapped_image().ljust(0x4000,b'\0');changed=bytearray(original)
        changed[0x1001]=2
        changed[0x1020:0x1026]=bytes.fromhex('e81b000000c3')
        changed[0x1040:0x1046]=bytes.fromhex('e81b000000c3');changed[0x1061]=6
        snapshot=root/'modified.bin';snapshot.write_bytes(changed)
        baseline=root/'baseline';baseline.mkdir()
        code,_=RawLifter(bytes.fromhex('b801000000c3')).lift(0x401000)
        (baseline/'shard_0000.c').write_text('#include "cpu.h"\n'+code)
        (baseline/'decls.h').write_text('#include "cpu.h"\nvoid sub_00401000(CPU*);\n')
        (baseline/'fntab.c').write_text('const uint32_t g_fn_addr[] = {0x00401000u};\n')
        hooks=root/'hooks.txt';hooks.write_text('')
        branches=root/'branches.txt';branches.write_text('')
        self.record(exe,baseline,hooks,branches)
        return exe,baseline,[('modified',snapshot)],hooks,branches

    def test_all_phase_closure_is_routed_and_standard_bodies_are_preserved(self):
        with tempfile.TemporaryDirectory()as temporary,patch.dict(os.environ,{'X87PC':'1'}):
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            output=root/'generated'
            result=generate(exe,baseline,snapshots,output,[0x401020],hooks,branches,
                            patch_ranges=[(0x401005,1)])
            self.assertEqual(result['extra_entries'],[0x401020,0x401040,0x401060])
            self.assertEqual(result['traps'],[])
            self.assertEqual(result['replaced_shards'],['shard_0000.c'])
            self.assertEqual(verify_routes(output,baseline,hooks,branches),result)
            self.assertEqual([row['entry']for row in result['functions']],
                             [0x401000,0x401020,0x401040,0x401060])
            (root/'hq_plugin.h').write_text('#include "cpu.h"\nint hq_plugin_enabled(void);\nvoid hq_plugin_route_error(CPU*,uint32_t);\n')
            harness=root/'check.c';harness.write_text('''
#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
uint8_t *g_mem;static int enabled;
int hq_plugin_enabled(void){return enabled;}
void hq_plugin_route_error(CPU*c,uint32_t a){(void)c;(void)a;exit(78);}
void sub_00401000(CPU*);void sub_00401020(CPU*);
int main(int argc,char**argv){
 g_mem=calloc(1,0x500000);assert(g_mem);FILE*f=fopen(argv[1],"rb");assert(f);
 assert(fread(g_mem+0x400000,1,0x4000,f)>=0x3000);fclose(f);
 CPU cpu={0},*c=&cpu;c->esp=0x8000;PUSH32(0xdeadbeef);sub_00401000(c);
 assert(c->eax==1&&c->eip==0xdeadbeef&&c->esp==0x8000);
 enabled=1;PUSH32(0xdeadbeef);sub_00401000(c);assert(c->eax==2&&c->esp==0x8000);
 PUSH32(0xdeadbeef);sub_00401020(c);assert(c->eax==6&&c->esp==0x8000&&c->eip==0xdeadbeef);
 if(argc>2){if(argv[2][0]=='f')g_mem[0x401005]=0x90;else g_mem[0x401001]=3;PUSH32(0xdeadbeef);sub_00401000(c);return 4;}
 free(g_mem);return 0;
}
''')
            binary=root/'check'
            build=subprocess.run(['clang','-O1','-Iruntime','-I'+str(root),'-I'+str(output),
                str(harness),str(output/'routes.c'),str(output/'variants.c'),
                str(output/'shard_0000.c'),'runtime/hq_route.c','-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary),str(snapshots[0][1])],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            unknown=subprocess.run([str(binary),str(snapshots[0][1]),'unknown'],capture_output=True)
            self.assertEqual(unknown.returncode,78)
            future=subprocess.run([str(binary),str(snapshots[0][1]),'future'],capture_output=True)
            self.assertEqual(future.returncode,78)
            (output/'routes.c').write_text('edited output')
            with self.assertRaisesRegex(ValueError,'route artifact differs'):
                verify_routes(output,baseline,hooks,branches)

    def test_bad_input_never_deletes_an_existing_cache(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            output=root/'generated';output.mkdir();sentinel=output/'sentinel';sentinel.write_text('keep')
            (output/'.hq-routes.json').write_text('{"producer":"hq-routes"}')
            snapshots[0][1].write_bytes(b'bad')
            with self.assertRaises(ValueError):generate(exe,baseline,snapshots,output,[],hooks,branches)
            self.assertEqual(sentinel.read_text(),'keep')

    def test_output_never_replaces_unmanaged_directories_or_links(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            output=root/'generated';output.mkdir();(output/'sentinel').write_text('keep')
            with self.assertRaisesRegex(ValueError,'unmanaged'):
                generate(exe,baseline,snapshots,output,[],hooks,branches)
            self.assertEqual((output/'sentinel').read_text(),'keep')
            link=root/'link';link.symlink_to(root/'missing')
            with self.assertRaisesRegex(ValueError,'symlink'):
                generate(exe,baseline,snapshots,link,[],hooks,branches)
            self.assertTrue(link.is_symlink())

    def test_unsupported_unchanged_continuation_does_not_replace_a_valid_cache(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            raw=bytearray(exe.read_bytes());raw[0x260:0x263]=bytes.fromhex('0f0bc3');exe.write_bytes(raw)
            image=bytearray(snapshots[0][1].read_bytes());image[0x1060:0x1063]=bytes.fromhex('0f0bc3')
            snapshots[0][1].write_bytes(image)
            self.record(exe,baseline,hooks,branches)
            output=root/'generated';output.mkdir();(output/'.hq-routes.json').write_text('{"producer":"hq-routes"}')
            sentinel=output/'sentinel';sentinel.write_text('keep')
            with self.assertRaisesRegex(ValueError,'unsupported|truncated'):
                generate(exe,baseline,snapshots,output,[0x401020],hooks,branches)
            self.assertEqual(sentinel.read_text(),'keep')

    def test_changed_existing_function_discovers_new_calls_without_extra_seeds(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            image=bytearray(snapshots[0][1].read_bytes())
            image[0x1000:0x1006]=bytes.fromhex('e81b000000c3');snapshots[0][1].write_bytes(image)
            result=generate(exe,baseline,snapshots,root/'generated',[],hooks,branches)
            self.assertEqual(result['extra_entries'],[0x401020,0x401040,0x401060])

    def test_cli_preserves_x87_precision_with_no_environment_flag(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            raw=bytearray(exe.read_bytes());raw[0x200:0x206]=bytes.fromhex('d9e8d9e8dec1');raw[0x206]=0xc3
            exe.write_bytes(raw)
            image=bytearray(snapshots[0][1].read_bytes());image[0x1000:0x1007]=bytes.fromhex('d9e8d9e8dec9c3')
            snapshots[0][1].write_bytes(image)
            self.record(exe,baseline,hooks,branches)
            environment=dict(os.environ);environment.pop('X87PC',None)
            run=subprocess.run([sys.executable,'tools/prepare_hq_routes.py','--exe',str(exe),
                '--gen',str(baseline),'--snapshot','modified='+str(snapshots[0][1]),
                '--out',str(root/'generated'),'--hooks',str(hooks),'--branches',str(branches)],
                capture_output=True,text=True,env=environment)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('X87R2(', (root/'generated/variants.c').read_text())

    def test_invalid_continuation_seeds_fail_without_touching_the_cache(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            for seed in (0x01000000,0x400100):
                with self.subTest(seed=seed),self.assertRaisesRegex(ValueError,'continuation'):
                    generate(exe,baseline,snapshots,root/'generated',[seed],hooks,branches)
                self.assertFalse((root/'generated').exists())

    def test_undecodable_suffix_cannot_become_a_fallthrough_native_body(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            raw=bytearray(exe.read_bytes());raw[0x3fe:0x400]=bytes.fromhex('900f');exe.write_bytes(raw)
            image=bytearray(snapshots[0][1].read_bytes());image[0x11fe:0x1200]=bytes.fromhex('900f')
            snapshots[0][1].write_bytes(image)
            self.record(exe,baseline,hooks,branches)
            for seed in (0x4011ff,0x4011fe):
                with self.subTest(seed=seed),self.assertRaisesRegex(ValueError,'decoded|fallthrough'):
                    generate(exe,baseline,snapshots,root/'generated',[seed],hooks,branches)
                self.assertFalse((root/'generated').exists())

    def test_stale_preserved_bodies_and_hooks_are_rejected_before_cache_replacement(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            output=root/'generated';output.mkdir();(output/'.hq-routes.json').write_text('{"producer":"hq-routes"}')
            sentinel=output/'sentinel';sentinel.write_text('keep')
            shard=baseline/'shard_0000.c';original=shard.read_text()
            shard.write_text(original.replace('0x1u','0x63u'))
            with self.assertRaisesRegex(ValueError,'provenance'):
                generate(exe,baseline,snapshots,output,[],hooks,branches)
            self.assertEqual(sentinel.read_text(),'keep')
            shard.write_text(original);hooks.write_text('0x401000')
            with self.assertRaisesRegex(ValueError,'provenance'):
                generate(exe,baseline,snapshots,output,[],hooks,branches)
            self.assertEqual(sentinel.read_text(),'keep')

    def test_inline_baseline_is_rejected_instead_of_bypassing_wrappers(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);exe,baseline,snapshots,hooks,branches=self.fixture(root)
            with patch.dict(os.environ,{'INLINE':'1'}):self.record(exe,baseline,hooks,branches)
            with self.assertRaisesRegex(ValueError,'unsupported baseline'):
                generate(exe,baseline,snapshots,root/'generated',[],hooks,branches)
            self.assertFalse((root/'generated').exists())


if __name__=='__main__':unittest.main()
