from pathlib import Path
import hashlib
import re
import subprocess
import tempfile
import unittest

MODULE=Path('out/installed/.nfsmw/full/scripts/NFSMW_XenonEffects.asi')
INI=MODULE.with_suffix('.ini')

@unittest.skipUnless(MODULE.is_file()and INI.is_file(),'requires the optional pinned local Xenon ASI and settings')
class XenonConfigTests(unittest.TestCase):
    def test_original_delayed_wrapper_calls_game_then_native_config_then_original_init(self):
        import pefile
        from tools.lift import RawLifter
        self.assertEqual(hashlib.sha256(MODULE.read_bytes()).hexdigest(),'5dcad612125be0f13426644b044a2a18874fc2d84726c033e97975e262256692')
        image=pefile.PE(str(MODULE));image.relocate_image(0x02400000)
        lifter=RawLifter(image.get_data(0x4940,0x25),base=0x02404940,x87pc=True)
        lifted,_=lifter.lift(0x02404940)
        self.assertIn('dispatch_indirect(c, 0x24030f0u)',lifted);self.assertIn('dispatch_indirect(c, 0x2404370u)',lifted)
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'config.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem,g_cbits[1u<<15];guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];static unsigned phase;
void sub_024030f0(CPU*),sub_02404370(CPU*);
int fileio_resolve_game(const char*name,char*out,size_t n){assert(!strcmp(name,"scripts/NFSMW_XenonEffects.ini"));
 return snprintf(out,n,"out/installed/.nfsmw/full/scripts/NFSMW_XenonEffects.ini")<(int)n;}
void hq_capture(CPU*c,const char*name,uint32_t address){(void)c;assert(phase==1&&!strcmp(name,"xenonconfig")&&address==0x024030f0);phase=2;}
void dispatch_indirect(CPU*c,uint32_t address){if(address==0x24030f0){sub_024030f0(c);return;}if(address==0x2404370){sub_02404370(c);return;}assert(!phase&&address==0x401234&&MR32(c->esp+4)==11&&MR32(c->esp+8)==22);phase=1;POP32(c->eip);c->eax=1;}
void sub_02404370(CPU*c){assert(phase==2&&MR32(0x024131d8)==2048&&MR32(0x024131d4)==100);
assert(MR8(0x024130ba)==1&&!MR8(0x024130bb)&&MR8(0x02413779)==0xa5);phase=3;POP32(c->eip);c->eax=0;}
'''+lifted+'''
int main(void){g_mem=calloc(1,0x02500000);memset(g_cbits,255,sizeof g_cbits);MR32(0x0241377c)=0x401234;MR8(0x02413779)=0xa5;
CPU c={0};c.esp=0x1000;c.ebp=0x76543210;c.ebx=0x12345678;MR32(c.esp)=0xdeadbeef;MR32(c.esp+4)=11;MR32(c.esp+8)=22;
sub_02404940(&c);assert(phase==3&&c.eax==1&&c.esp==0x1004&&c.eip==0xdeadbeef&&c.ebp==0x76543210&&c.ebx==0x12345678);free(g_mem);}
''')
            result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-Iruntime',str(source),'runtime/hq_plugin.c','runtime/hq_config.c','-o',str(root/'config')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'config')],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
