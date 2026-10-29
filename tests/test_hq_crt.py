from pathlib import Path
import subprocess
import tempfile
import unittest

class CRTTests(unittest.TestCase):
    def test_lifecycle_math_and_cdecl_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include "hq_crt.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;static uint32_t next=0x8000,called[8],count;
uint32_t gheap_alloc(int h,uint32_t n,int z){(void)h;uint32_t p=next;next+=(n+15)&~15u;if(z)memset(g_mem+p,0,n);return p;}
void gheap_free(int h,uint32_t p){(void)h;(void)p;}
uint32_t gheap_usize(uint32_t p){(void)p;return 32;}
uint32_t call_guest(CPU*c,uint32_t f,int n,const uint32_t*a){(void)n;(void)a;called[count++]=f;assert(c->ecx==0xabcdef);return f==0x333?7:0;}
int msvcrt_call(CPU*c,const char*n,uint32_t*r){(void)c;(void)n;(void)r;return 0;}
uint32_t guest_vformat(uint32_t o,uint32_t cap,const char*f,uint32_t va){(void)o;(void)cap;(void)f;(void)va;return 0;}
int main(void){g_mem=calloc(1,0x100000);CPU cpu={0},*c=&cpu;c->esp=0x100;c->ecx=0xabcdef;uint32_t r;
assert(hq_crt_dll("api-ms-win-crt-runtime-l1-1-0.dll"));assert(!hq_crt_dll("kernel32.dll"));
MR32(c->esp)=0x200;MR32(c->esp+4)=0x208;MR32(0x200)=0x111;MR32(0x204)=0x222;
assert(hq_crt_call(c,"_initterm",&r)&&!r&&count==2&&called[0]==0x111&&called[1]==0x222&&c->esp==0x100&&c->ecx==0xabcdef);
count=0;MR32(0x200)=0x333;assert(hq_crt_call(c,"_initterm_e",&r)&&r==7&&count==1);
MR32(c->esp)=0x300;assert(hq_crt_call(c,"_initialize_onexit_table",&r)&&!r);
MR32(c->esp+4)=0x111;assert(hq_crt_call(c,"_register_onexit_function",&r)&&!r);
MR32(c->esp+4)=0x222;assert(hq_crt_call(c,"_register_onexit_function",&r)&&!r);
count=0;assert(hq_crt_call(c,"_execute_onexit_table",&r)&&!r&&count==2&&called[0]==0x222&&called[1]==0x111);
c->xmm[0].f[0]=0.25f;c->xmm[0].u32[1]=0x12345678;assert(hq_crt_call(c,"__libm_sse2_tanf",&r));assert(fabsf(c->xmm[0].f[0]-tanf(.25f))<1e-6&&c->xmm[0].u32[1]==0x12345678);
c->top=3;ST(0)=3;ST(1)=17;assert(hq_crt_call(c,"_CIfmod",&r)&&c->top==4&&ST(0)==2);
MRF64(c->esp)=1.2;assert(hq_crt_call(c,"ceil",&r)&&ST(0)==2&&c->top==3);
assert(!hq_crt_call(c,"unimplemented",&r));free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/hq_crt.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
