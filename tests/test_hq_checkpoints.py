from pathlib import Path
import hashlib
import json
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

class CheckpointTests(unittest.TestCase):
    def test_captured_values_require_complete_compiled_consumer_coverage(self):
        from tools import prepare_hq_checkpoints as helper
        image=bytearray(1024);image[:2]=b'MZ';struct.pack_into('<I',image,0x3c,0x80)
        image[0x80:0x84]=b'PE\0\0';struct.pack_into('<HH',image,0x84,0x14c,1)
        struct.pack_into('<H',image,0x94,224);optional=0x98;struct.pack_into('<H',image,optional,0x10b)
        for offset,value in ((16,0x1000),(28,0x400000),(32,0x1000),(36,0x200),(56,0x2000),(60,0x200),(92,16)):
            struct.pack_into('<I',image,optional+offset,value)
        section=optional+224;image[section:section+8]=b'.text\0\0\0'
        struct.pack_into('<IIII',image,section+8,512,0x1000,512,512)
        struct.pack_into('<III',image,512,1,1,150);image[524:526]=bytes((7,0x74))
        schema={'points':[{'id':1,'fields':[{'address':0x401000,'consumer':0x401000},{'address':0x401004,'consumer':0x401000}]},
                          {'id':2,'fields':[{'address':0x401008,'consumer':0x401008}]},
                          {'id':3,'fields':[{'address':0x40100c,'consumer':0x40100c,'size':1},{'address':0x40100d,'consumer':0x40100c,'size':1}]}]}
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);output=root/'checkpoints.c';(root/'image0.exe').write_bytes(image)
            changed=bytearray(image);struct.pack_into('<III',changed,512,97,97,150);changed[524:526]=bytes((0,0xeb));(root/'image1.exe').write_bytes(changed)
            manifest={'phases':['standard','captured'],'functions':[{'entry':0x401000,'ranges':[[0x401000,8]]},{'entry':0x401008,'ranges':[[0x401008,4]]},{'entry':0x40100c,'ranges':[[0x40100c,2]]}]}
            (root/'manifest.json').write_text(json.dumps(manifest))
            with patch.object(helper,'CANONICAL',hashlib.sha256(image).hexdigest()),patch.object(helper,'SCHEMA',schema),patch.object(helper,'FIELDS',((0x401000,0x401004),(0x401008,),(0x40100c,0x40100d))):
                helper.prepare(root,output)
                code=root/'test.c';code.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;int hq_checkpoint_known(unsigned);
int main(void){g_mem=calloc(1,0x402000);MR32(0x401000)=97;MR32(0x401004)=97;MR32(0x401008)=150;
assert(hq_checkpoint_known(1)&&hq_checkpoint_known(2));MR8(0x40100c)=0;MR8(0x40100d)=0xeb;assert(hq_checkpoint_known(3));MR8(0x40100e)=0xff;assert(hq_checkpoint_known(3));MR8(0x40100c)=1;assert(!hq_checkpoint_known(3));MR32(0x401004)=96;assert(!hq_checkpoint_known(1));
MR32(0x401008)=151;assert(!hq_checkpoint_known(2)&&!hq_checkpoint_known(0));free(g_mem);}
''')
                result=subprocess.run(['clang','-O1','-Iruntime',str(code),str(output),'-o',str(root/'test')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                result=subprocess.run([str(root/'test')],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
                previous=output.read_bytes();manifest['functions'][0]['ranges']=[[0x401000,7]]
                (root/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError,'missing from route coverage'):helper.prepare(root,output)
                self.assertEqual(output.read_bytes(),previous)
                (root/'image0.exe').write_bytes(image+b'changed')
                with self.assertRaisesRegex(ValueError,'canonical image'):helper.prepare(root,output)
                self.assertEqual(output.read_bytes(),previous)

if __name__=='__main__':unittest.main()
