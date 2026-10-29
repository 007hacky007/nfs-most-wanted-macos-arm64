from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.hq_module_catalog import MODULES, validate_catalog, verify_inputs,render_c_catalog
from tools.prepare_hq_modules import prepare_modules, normalize_continuations, extra_entrypoints
from tools.lift import RawLifter


def fixture_dll():
    data=bytearray(0x600);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,0x80)
    data[0x80:0x84]=b'PE\0\0';struct.pack_into('<HHIIIHH',data,0x84,0x14c,2,0,0,0,0xe0,0x2102)
    opt=0x98;struct.pack_into('<H',data,opt,0x10b)
    for offset,value in [(16,0x1000),(20,0x1000),(28,0x10000000),(32,0x1000),(36,0x200),
                         (56,0x4000),(60,0x200),(92,16),(96+5*8,0x3000),(100+5*8,12)]:
        struct.pack_into('<I',data,opt+offset,value)
    section=opt+0xe0
    for n,name,virtual,raw,flags in [(0,b'.text',0x1000,0x200,0x60000020),(1,b'.reloc',0x3000,0x400,0x42000040)]:
        at=section+n*40;data[at:at+len(name)]=name
        struct.pack_into('<IIII',data,at+8,0x200,virtual,0x200,raw);struct.pack_into('<I',data,at+36,flags)
    data[0x200:0x202]=b'\x90\xc3';struct.pack_into('<I',data,0x208,0x10001000)
    struct.pack_into('<IIHH',data,0x400,0x1000,12,0x3008,0)
    return bytes(data)


def fixture_module(data):
    return replace(MODULES[1],key='fixture',path='scripts/fixture.dll',
                   sha256=hashlib.sha256(data).hexdigest(),size=len(data),image_size=0x4000,
                   entry=0x01001000,prefix='fixture_',tls=None,init=(),wrappers=())


class HQModuleCatalogTests(unittest.TestCase):
    def test_generated_native_catalog_keeps_prefixes_and_verified_tls(self):
        source=render_c_catalog()
        self.assertIn('HQ_MODULE(dx_,UINT32_MAX,0u,0u,0u)',source)
        self.assertIn('HQ_MODULE(x360_,128u,0x01020748u,8u,0x0102f644u)',source)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'catalog.inc').write_text(source)
            path=root/'catalog.c';binary=root/'catalog'
            path.write_text('''#include <stdint.h>
#include <assert.h>
static const uint32_t slots[]={
#define HQ_MODULE(prefix,slot,start,size,index) slot,
#include "catalog.inc"
#undef HQ_MODULE
};
int main(void){assert(sizeof slots/sizeof *slots==6&&slots[0]==UINT32_MAX);
for(unsigned i=1;i<6;i++)assert(slots[i]==127+i);return 0;}
''')
            build=subprocess.run(['clang','-O1',str(path),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            self.assertEqual(subprocess.run([str(binary)]).returncode,0)
    def test_disjoint_ids_ranges_tls_and_delayed_initialization(self):
        validate_catalog(MODULES)
        self.assertEqual([m.module_id for m in MODULES],list(range(1,7)))
        self.assertEqual([m.tls.index for m in MODULES if m.tls],list(range(128,133)))
        self.assertEqual(MODULES[-1].init[-1].timing,'game_startup')
        with self.assertRaisesRegex(ValueError,'overlap'):
            validate_catalog([MODULES[1],replace(MODULES[2],base=MODULES[1].base)])

    def test_debug_entrypoints_are_bound_to_the_exact_module(self):
        entries=extra_entrypoints(MODULES[1])
        self.assertEqual(len(entries),429)
        self.assertTrue(set(MODULES[1].wrappers)<=set(entries))
        self.assertEqual(extra_entrypoints(MODULES[2]),())
        with self.assertRaisesRegex(ValueError,'entrypoint metadata'):
            extra_entrypoints(replace(MODULES[1],sha256='0'*64))

    def test_case_insensitive_lookup_and_hash_before_outputs(self):
        data=fixture_dll();module=fixture_module(data)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'Scripts').mkdir();source=root/'Scripts/FIXTURE.DLL';source.write_bytes(data)
            self.assertEqual(verify_inputs(root,[module]),[source])
            source.write_bytes(data[:-1]+b'x')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                verify_inputs(root,[module])
            with patch('tools.prepare_hq_modules.subprocess.run')as run:
                with self.assertRaises(ValueError):prepare_modules(root,root/'out',root/'gen',[module])
                run.assert_not_called();self.assertFalse((root/'out').exists())

    def test_symlink_and_case_collision_are_rejected(self):
        data=fixture_dll();module=fixture_module(data)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'original').write_bytes(data)
            (root/'scripts/fixture.dll').symlink_to(root/'original')
            with self.assertRaisesRegex(ValueError,'symlink'):verify_inputs(root,[module])
            (root/'scripts/fixture.dll').unlink();(root/'scripts/fixture.dll').write_bytes(data)
            (root/'scripts/FIXTURE.DLL').write_bytes(data)
            if len(list((root/'scripts').iterdir()))==2:
                with self.assertRaisesRegex(ValueError,'ambiguous'):verify_inputs(root,[module])

    def test_complete_batch_is_verified_before_writing(self):
        data=fixture_dll();first=fixture_module(data);second=replace(first,key='second',module_id=3,base=0x1400000,entry=0x1401000,prefix='second_',path='scripts/missing.dll')
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'scripts/fixture.dll').write_bytes(data)
            with patch('tools.prepare_hq_modules.subprocess.run')as run:
                with self.assertRaisesRegex(ValueError,'missing'):prepare_modules(root,root/'out',root/'gen',[first,second])
                run.assert_not_called();self.assertFalse((root/'out').exists())

    def test_dangling_output_link_is_rejected_before_any_cache_replacement(self):
        data=fixture_dll();first=fixture_module(data)
        second=replace(first,key='second',module_id=3,base=0x1400000,entry=0x1401000,
                       prefix='second_',path='scripts/second.dll')
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir()
            for name in ('fixture.dll','second.dll'):(root/'scripts'/name).write_bytes(data)
            existing=root/'gen/fixture';existing.mkdir(parents=True)
            (existing/'.hq-generated.json').write_text('{"key":"fixture"}')
            (existing/'sentinel').write_text('keep')
            (root/'gen/second').symlink_to(root/'missing')
            with self.assertRaisesRegex(ValueError,'symlink'):
                prepare_modules(root,root/'out',root/'gen',[first,second],shards=1)
            self.assertEqual((existing/'sentinel').read_text(),'keep')
            self.assertFalse((root/'out').exists())

    def test_changed_processor_never_replaces_a_generated_cache(self):
        data=fixture_dll();module=fixture_module(data)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'scripts/fixture.dll').write_bytes(data)
            existing=root/'gen/fixture';existing.mkdir(parents=True)
            (existing/'.hq-generated.json').write_text('{"key":"fixture"}')
            sentinel=existing/'sentinel';sentinel.write_text('keep')
            with patch('tools.prepare_hq_modules.processor_hashes',side_effect=[{'tool':'before'},{'tool':'after'}]):
                with self.assertRaisesRegex(ValueError,'inputs changed'):
                    prepare_modules(root,root/'out',root/'gen',[module],shards=1)
            self.assertEqual(sentinel.read_text(),'keep')
            self.assertFalse((root/'out/modules.json').exists())

    def test_unmanaged_catalog_is_rejected_before_any_output_is_written(self):
        data=fixture_dll();module=fixture_module(data)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'scripts/fixture.dll').write_bytes(data)
            (root/'gen').mkdir();catalog=root/'gen/catalog.inc';catalog.write_text('user file')
            with self.assertRaisesRegex(ValueError,'unmanaged module catalog'):
                prepare_modules(root,root/'out',root/'gen',[module],shards=1)
            self.assertEqual(catalog.read_text(),'user file');self.assertFalse((root/'out').exists())

    def test_real_generation_uses_synthetic_input_and_restores_real_entrypoints(self):
        data=fixture_dll();module=fixture_module(data)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir();source=root/'scripts/fixture.dll';source.write_bytes(data)
            result=prepare_modules(root,root/'out',root/'gen',[module],shards=1)
            self.assertEqual(result['modules'][0]['key'],'fixture')
            self.assertEqual(source.read_bytes(),data)
            text=''.join(p.read_text()for p in(root/'gen/fixture').glob('*.c'))
            self.assertIn('g_fixture_fn_count',text);self.assertIn('void sub_01001000(',text)
            self.assertNotIn('_body(',text)
            prepared=json.loads((root/'gen/fixture/.hq-generated.json').read_text())
            self.assertEqual(prepared['artifacts']['shard_0000.c'],
                             hashlib.sha256((root/'gen/fixture/shard_0000.c').read_bytes()).hexdigest())
            self.assertIn('tools/lift.py',prepared['raw_generation']['tools'])
            self.assertFalse((root/'gen/fixture/generation-manifest.json').exists())
            self.assertNotIn(str(root), (root/'out/modules.json').read_text())
            # Repeated generation replaces only its own marked generated directory.
            (root/'gen/fixture/stale.c').write_text('obsolete')
            prepare_modules(root,root/'out',root/'gen',[module],shards=1)
            self.assertFalse((root/'gen/fixture/stale.c').exists())

    def test_exact_push_return_normalization_retains_original_frame(self):
        source='''/* 0180ac78 push 0x6690c0 */\nPUSH32(0x6690c0u);
/* 0180ac7d ret */\nPOP32(c->eip); return;\n'''
        fixed,records=normalize_continuations(source,(0x401000,0x849000))
        self.assertIn('DISPATCH_TAIL(c, 0x6690c0u)',fixed)
        self.assertEqual(records,[{'site':0x180ac78,'target':0x6690c0}])
        unchanged,_=normalize_continuations(source,(0x700000,0x849000));self.assertEqual(unchanged,source)
        data_target=source.replace('6690c0','900000')
        unchanged,records=normalize_continuations(data_target)
        self.assertEqual(unchanged,data_target);self.assertEqual(records,[])

    def test_d3dx_keeps_the_tested_unpruned_dispatch_profile(self):
        data=fixture_dll();module=replace(fixture_module(data),module_id=1)
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'scripts/fixture.dll').write_bytes(data)
            prepare_modules(root,root/'out',root/'gen',[module],shards=1)
            prepared=json.loads((root/'gen/fixture/.hq-generated.json').read_text())
            self.assertFalse(prepared['raw_generation']['options']['JTSWITCH'])

    def test_lifted_cave_resumes_game_with_original_stack_and_live_registers(self):
        # Synthetic MOV/PUSH/RET cave, followed by a callee-cleanup game continuation.
        with patch.dict(os.environ,{'COMMENTS':'1'}):
            code,_=RawLifter(bytes.fromhex('b82a0000006800204000c3'),base=0x1801000).lift(0x1801000)
        code,records=normalize_continuations(code)
        self.assertEqual(records,[{'site':0x1801005,'target':0x402000}])
        source=r'''
#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;static unsigned calls;
void dispatch_indirect(CPU*c,uint32_t address){
 assert(address==0x402000&&c->eax==42&&c->esp==0x7ff4);
 assert(c->cf==1&&c->zf==0&&c->ebx==123);
 assert(c->st[c->top&7]==2.5&&c->fcw==0x027f);
 assert(MR32(c->esp)==0xdeadbeef&&MR32(c->esp+4)==7&&MR32(c->esp+8)==8);
 calls++;c->eax+=MR32(c->esp+4)+MR32(c->esp+8);POP32(c->eip);c->esp+=8;
}
'''+code+r'''
int main(void){
 g_mem=calloc(1,0x10000);assert(g_mem);CPU cpu={0},*c=&cpu;
 c->esp=0x8000;c->ebx=123;c->cf=1;c->st[0]=2.5;c->fcw=0x027f;
 PUSH32(8);PUSH32(7);PUSH32(0xdeadbeef);sub_01801000(c);
 assert(calls==1&&c->eax==57&&c->esp==0x8000&&c->eip==0xdeadbeef);
 assert(c->cf==1&&c->ebx==123&&c->st[0]==2.5);free(g_mem);return 0;
}
'''
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);path=root/'cave.c';path.write_text(source);binary=root/'cave'
            build=subprocess.run(['clang','-O1','-Iruntime',str(path),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)

    @unittest.skipUnless(Path('out/installed/.nfsmw/full/scripts/X360Stuff.asi').is_file(),'requires local supplied HQ files')
    def test_actual_supplied_modules_match_catalog(self):
        self.assertEqual(len(verify_inputs(Path('out/installed'),MODULES)),6)


if __name__=='__main__':unittest.main()
