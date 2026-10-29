from pathlib import Path
import subprocess
import tempfile
import unittest


class TLSTests(unittest.TestCase):
    def test_static_tls_is_separate_per_thread_and_avoids_dynamic_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include "hq_tls.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem,g_cbits[1u<<15];static uint32_t next=0x10000,freed;
uint32_t gheap_alloc(int h,uint32_t n,int z){assert(h==1&&n==8&&z);uint32_t p=next;next+=32;return p;}
void gheap_free(int h,uint32_t p){assert(h==1);freed=p;}
int main(void){g_mem=calloc(1,0x2000000);memset(g_cbits,255,sizeof g_cbits);
 CPU first={0},second={0};first.fs_base=0x1000;second.fs_base=0x3000;
 MR32(0x102c)=0x2000;MR32(0x302c)=0x4000;MR32(0x2000)=0x777;MR32(0x4000)=0x888;
 MR32(0x01020748)=42;MR32(0x0102074c)=0x80000000;
 assert(hq_tls_enable(0x01020748,8,0x0102f644));assert(MR32(0x0102f644)==128);
 CPU before=first;assert(hq_tls_attach(&first));assert(!memcmp(&first,&before,sizeof first));
 uint32_t a=MR32(0x2000+128*4);assert(a&&MR32(a)==42&&MR32(a+4)==0x80000000);
 MR32(a+4)=1;assert(hq_tls_attach(&first)&&MR32(a+4)==1);
 assert(hq_tls_attach(&second));uint32_t b=MR32(0x4000+128*4);
 assert(a!=b&&MR32(b+4)==0x80000000&&MR32(0x2000)==0x777&&MR32(0x4000)==0x888);
 hq_tls_detach(&first);assert(freed==a&&!MR32(0x2000+128*4)&&MR32(b+4)==0x80000000);
 assert(hq_tls_attach(&first)&&MR32(0x2000+128*4)!=a);free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(source),
                            'runtime/hq_tls.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


    def test_five_module_templates_are_distinct_for_each_thread(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);source=root/'modules.c'
            source.write_text('''#include "cpu.h"
#include "hq_tls.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem,g_cbits[1u<<15];static uint32_t next=0x10000,freed;
uint32_t gheap_alloc(int h,uint32_t n,int zero){assert(h==1&&n==8&&zero);uint32_t p=next;next+=16;return p;}
void gheap_free(int h,uint32_t p){assert(h==1&&p);freed++;}
int main(void){g_mem=calloc(1,0x2000000);memset(g_cbits,255,sizeof g_cbits);
CPU a={0},b={0};a.fs_base=0x1000;b.fs_base=0x3000;MR32(0x102c)=0x2000;MR32(0x302c)=0x4000;
for(unsigned i=0;i<5;i++){MR32(0x8000+i*8)=100+i;MR32(0x8004+i*8)=200+i;
 assert(hq_tls_enable_slot(0x8000+i*8,8,0x9000+i*4,128+i));assert(MR32(0x9000+i*4)==128+i);}
assert(!hq_tls_enable_slot(0x8000,8,0x9100,127));assert(!hq_tls_enable_slot(0x8000,8,0x9100,133));
CPU before=a;assert(hq_tls_attach(&a)&&hq_tls_attach(&b));assert(!memcmp(&a,&before,sizeof a));
for(unsigned i=0;i<5;i++){uint32_t p=MR32(0x2000+(128+i)*4),q=MR32(0x4000+(128+i)*4);
 assert(p&&q&&p!=q&&MR32(p)==100+i&&MR32(q+4)==200+i);MR32(p)=900+i;
 assert(hq_tls_attach(&a)&&MR32(p)==900+i&&MR32(q)==100+i);}
hq_tls_detach(&a);assert(freed==5);
for(unsigned i=0;i<5;i++)assert(!MR32(0x2000+(128+i)*4)&&MR32(0x4000+(128+i)*4));
hq_tls_detach(&b);assert(freed==10);free(g_mem);}
''')
            result=subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/hq_tls.c','-o',str(root/'modules')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(root/'modules')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
