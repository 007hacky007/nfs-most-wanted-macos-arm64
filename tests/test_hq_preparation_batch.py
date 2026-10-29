"""Exercise the real preparation loop across the ExtraOptions/Xenon boundary."""
from dataclasses import replace
import json
import os
import struct
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    from .test_hq_module_catalog import fixture_dll, fixture_module
except ImportError:
    from test_hq_module_catalog import fixture_dll, fixture_module
from tools.prepare_hq_modules import prepare_modules


class HQPreparationBatchTests(unittest.TestCase):
    def test_extraoptions_adapter_preserves_shard_count_for_xenon(self):
        data=fixture_dll();base=fixture_module(data)
        modules=(replace(base,key='extraoptions',module_id=5,base=0x01c00000,entry=0x01c01000,
                         prefix='extraopts_',path='scripts/extraoptions.dll'),
                 replace(base,key='xenon',module_id=6,base=0x02400000,entry=0x02401000,
                         prefix='xenon_',path='scripts/xenon.dll'))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'scripts').mkdir()
            for module in modules:(root/module.path).write_bytes(data)
            # The adapter's six pinned sites have their own real CRT tests.
            # Keep its mapping input/output contract while running both real generators.
            with patch('tools.prepare_hq_modules.validate_extraoptions_environment') as validate, \
                 patch('tools.prepare_hq_modules.adapt_extraoptions_environment',side_effect=lambda sources:dict(sources)) as adapt, \
                 patch('tools.prepare_hq_modules.subprocess.run',wraps=subprocess.run) as run:
                result=prepare_modules(root,root/'out',root/'gen',modules,shards=1)
            validate.assert_called_once_with(data,modules[0].base)
            adapt.assert_called_once();self.assertEqual(set(adapt.call_args.args[0]),{'shard_0000.c'})
            generators=[call.args[0] for call in run.call_args_list if Path(call.args[0][1]).name=='genall.py']
            self.assertEqual(len(generators),2)
            self.assertEqual([command[-1] for command in generators],['1','1'])
            self.assertEqual([module['key'] for module in result['modules']],['extraoptions','xenon'])
            self.assertEqual(json.loads((root/'out/modules.json').read_text()),json.loads(json.dumps(result)))
            for module in modules:
                generated=root/'gen'/module.key
                prepared=json.loads((generated/'.hq-generated.json').read_text())
                self.assertEqual(prepared['module']['module_id'],module.module_id)
                self.assertEqual(prepared['raw_generation']['options']['SYMPFX'],module.prefix)
                self.assertTrue(prepared['raw_generation']['options']['JTSWITCH'])
                self.assertTrue((generated/'shard_0000.c').is_file())


    def test_inherited_reteip_zero_cannot_disable_game_continuations(self):
        raw=bytearray(fixture_dll())
        raw[0x200:0x206]=b'\x68'+struct.pack('<I',0x668370)+b'\xc3'
        raw=bytes(raw);module=fixture_module(raw)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/module.path).write_bytes(raw)
            with patch.dict(os.environ,{'RETEIP':'0'}):
                result=prepare_modules(root,root/'out',root/'gen',[module],shards=1)
            generated=root/'gen'/module.key
            provenance=json.loads((generated/'.hq-generated.json').read_text())
            self.assertTrue(provenance['raw_generation']['options']['RETEIP'])
            self.assertEqual(result['modules'][0]['continuations'],[{'site':module.entry,'target':0x668370}])
            harness=root/'continuation.c'
            harness.write_text(r"""
#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
#include "shard_0000.c"
uint8_t *g_mem;static unsigned called;
void dispatch_indirect(CPU*c,uint32_t target){
 assert(target==0x668370&&c->esp==0x8000&&MR32(c->esp)==0xdeadbeef);
 assert(c->eax==42&&c->ebx==123&&c->cf==1&&c->zf==0);
 assert(c->fcw==0x027f&&c->st[c->top&7]==2.5);
 called++;c->eax+=MR32(c->esp+4)+MR32(c->esp+8);POP32(c->eip);c->esp+=8;
}
int main(void){
 g_mem=calloc(1,0x10000);assert(g_mem);CPU cpu={0},*c=&cpu;
 c->esp=0x8000;c->eax=42;c->ebx=123;c->cf=1;c->fcw=0x027f;c->st[0]=2.5;
 MR32(c->esp)=0xdeadbeef;MR32(c->esp+4)=7;MR32(c->esp+8)=8;
 sub_01001000(c);
 assert(called==1&&c->eax==57&&c->esp==0x800c&&c->eip==0xdeadbeef);
 assert(c->ebx==123&&c->cf==1&&c->fcw==0x027f&&c->st[0]==2.5);
 free(g_mem);return 0;
}
""")
            binary=root/'continuation'
            compiled=subprocess.run(['clang','-O1','-Iruntime','-I'+str(generated),str(harness),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
