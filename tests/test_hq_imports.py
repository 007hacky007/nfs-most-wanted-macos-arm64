from pathlib import Path
import subprocess
import tempfile
import unittest

class ImportTests(unittest.TestCase):
    def test_d3dx_alias_preserves_cpu_and_original_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include "hq_import.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
uint8_t *g_mem;static CPU before;static int loaded,calls;static const char *wanted;static uint32_t cleanup;
uint32_t module_by_name(const char*n){assert(!strcmp(n,"d3dx9_26.dll"));return loaded?0x2000000:0;}
uint32_t module_load(CPU*c,const char*n,uint32_t*err){(void)n;memset(c,0xcc,sizeof *c);loaded=1;*err=0;return 0x2000000;}
uint32_t module_proc(uint32_t h,uint32_t n,uint32_t*err){assert(h==0x2000000);assert(!strcmp((char*)g_mem+n,wanted));*err=0;return 0x2001234;}
uint32_t gheap_alloc(int h,uint32_t n,int z){(void)h;(void)n;(void)z;return 0x200;}
void gheap_free(int h,uint32_t p){(void)h;assert(p==0x200);}
void dispatch_indirect(CPU*c,uint32_t fn){assert(fn==0x2001234);assert(!memcmp(c,&before,sizeof *c));assert(MR32(c->esp)==0x11223344);calls++;c->eax=123;POP32(c->eip);c->esp+=cleanup;}
int main(void){g_mem=calloc(1,4096);CPU c;
const char *names[]={"D3DXCreateEffect","D3DXCreateTextureFromFileInMemory"};
for(unsigned i=0;i<2;i++){wanted=names[i];cleanup=i?16:36;memset(&c,0x12,sizeof c);c.esp=0x400;MR32(c.esp)=0x11223344;before=c;
assert(hq_import_forward(&c,"d3dx9_43.dll",wanted));assert(c.eax==123&&c.esp==before.esp+cleanup+4&&c.eip==0x11223344&&calls==(int)i+1);}
before=c;assert(!hq_import_forward(&c,"kernel32.dll","D3DXCreateEffect"));assert(!memcmp(&c,&before,sizeof c));free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/hq_import.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
