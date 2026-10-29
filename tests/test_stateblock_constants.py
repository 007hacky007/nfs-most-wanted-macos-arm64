"""Recorded shader constants own their values across source-buffer reuse."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


class StateBlockConstantsTests(unittest.TestCase):
    def test_record_capture_apply_and_release_all_constant_types(self):
        prefix = Path('tests/backend_com_sm3.c').read_text().split('static void rain_fvf(')[0]
        prefix = prefix.replace('#include "../runtime/com.c"',
                                '#include "' + str(Path('runtime/com.c').resolve()) + '"')
        allocator = r'''
#include <stdlib.h>
#include <assert.h>
static void *payloads[32];static unsigned allocated,released;static int watch_alloc,fail_alloc;
static void *checked_malloc(size_t size){
 if(fail_alloc)return NULL;void*p=malloc(size);
 if(watch_alloc&&p){assert(allocated<32);payloads[allocated++]=p;}return p;
}
static void checked_free(void*p){
 if(p)for(unsigned i=0;i<allocated;i++)if(payloads[i]==p){payloads[i]=NULL;released++;break;}
 free(p);
}
#define malloc checked_malloc
#define free checked_free
'''
        body = r'''
static const char *setters[]={"SetVertexShaderConstantF","SetPixelShaderConstantF",
 "SetVertexShaderConstantI","SetPixelShaderConstantI","SetVertexShaderConstantB","SetPixelShaderConstantB"};
static const char *getters[]={"GetVertexShaderConstantF","GetPixelShaderConstantF",
 "GetVertexShaderConstantI","GetPixelShaderConstantI","GetVertexShaderConstantB","GetPixelShaderConstantB"};
static uint32_t word(unsigned type,unsigned value){float f=(float)value;uint32_t u;memcpy(&u,&f,4);return type<2?u:value;}
static void fill(unsigned type,unsigned value,unsigned count){
 unsigned words=count*(type<4?4:1);for(unsigned i=0;i<words;i++)MR32(0x18000+i*4)=word(type,value);
}
static void expect(CPU*c,uint32_t device,unsigned type,unsigned reg,unsigned count,unsigned value){
 uint32_t a[8]={reg,0x19000,count};assert(!invoke(c,IF_DEV,getters[type],device,a));
 for(unsigned i=0;i<count*(type<4?4:1);i++)assert(MR32(0x19000+i*4)==word(type,type==5?!!value:value));
}
int main(void){
 g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
 mem_commit(0x10000,0x10000);CPU c={0};uint32_t device=com_new(IF_DEV,16),a[8]={0};
 for(unsigned type=0;type<6;type++){
  fill(type,11,4);a[0]=1;a[1]=0x18000;a[2]=4;assert(!invoke(&c,IF_DEV,setters[type],device,a));
  assert(!invoke(&c,IF_DEV,"BeginStateBlock",device,a));
  fill(type,2,2);a[0]=2;a[1]=0x18000;a[2]=2;watch_alloc=1;
  assert(!invoke(&c,IF_DEV,setters[type],device,a));watch_alloc=0;
  expect(&c,device,type,1,4,11); /* recording does not change device state */
  a[0]=0x1a000;assert(!invoke(&c,IF_DEV,"EndStateBlock",device,a));uint32_t block=MR32(0x1a000);
  fill(type,99,2);assert(!invoke(&c,IF_STATEBLOCK,"Apply",block,a));
  expect(&c,device,type,2,2,2);expect(&c,device,type,1,1,11);expect(&c,device,type,4,1,11);
  unsigned captured=type<4?7:0;fill(type,captured,2);a[0]=2;a[1]=0x18000;a[2]=2;
  assert(!invoke(&c,IF_DEV,setters[type],device,a));assert(!invoke(&c,IF_STATEBLOCK,"Capture",block,a));
  fill(type,8,2);assert(!invoke(&c,IF_DEV,setters[type],device,a));fill(type,99,2);
  /* Applying and capturing must never access the original guest pointer. */
  g_cbits[0x18000>>17]&=~(1u<<((0x18000>>14)&7));
  assert(!invoke(&c,IF_STATEBLOCK,"Apply",block,a));
  mem_commit(0x18000,0x8000);expect(&c,device,type,2,2,captured);
  expect(&c,device,type,1,1,11);expect(&c,device,type,4,1,11);
  unsigned old=released;assert(!invoke(&c,IF_STATEBLOCK,"Release",block,a));assert(released==old+1);
  assert(!invoke(&c,IF_DEV,"BeginStateBlock",device,a));int slot=g_sb_rec;
  a[0]=2;a[1]=0;a[2]=0;fail_alloc=1;
  assert(!invoke(&c,IF_DEV,setters[type],device,a));fail_alloc=0;assert(!g_sb[slot].n);
  unsigned limit=type==0?256:type==1?224:16;
  const uint32_t invalid[][3]={{limit,0x18000,1},{limit-1,0x18000,2},{2,0,1},{2,0xfffffff0u,2},{2,0x30000,1},{2,0x1fffcu,2}};
  for(unsigned j=0;j<6;j++){memcpy(a,invalid[j],12);assert(invoke(&c,IF_DEV,setters[type],device,a)==0x8876086cu);assert(!g_sb[slot].n);}
  a[0]=limit-1;a[1]=0x18000;a[2]=1;fail_alloc=1;
  assert(invoke(&c,IF_DEV,setters[type],device,a)==0x8007000eu);fail_alloc=0;assert(!g_sb[slot].n);
  fill(type,2,1);watch_alloc=1;assert(!invoke(&c,IF_DEV,setters[type],device,a));watch_alloc=0;
  a[0]=0x1a000;assert(!invoke(&c,IF_DEV,"EndStateBlock",device,a));block=MR32(0x1a000);
  assert(!invoke(&c,IF_STATEBLOCK,"Apply",block,a));expect(&c,device,type,limit-1,1,2);
  assert(!invoke(&c,IF_STATEBLOCK,"Release",block,a));
 }
 assert(allocated==12&&released==12);return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);source = root/'test.c';binary = root/'test'
            source.write_text(allocator + prefix + body)
            flags = ['-O1', '-Iruntime', '-Wl,-undefined,dynamic_lookup']
            if os.environ.get('NFSMW_STATEBLOCK_SANITIZE') == '1':
                flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            result = subprocess.run(['clang', *flags, str(source), 'runtime/vsemu.c', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
