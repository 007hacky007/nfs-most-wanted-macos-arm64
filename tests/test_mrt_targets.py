"""COM render-target slots reach the backend without changing slot zero."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires native COM fixture')
class MRTTargets(unittest.TestCase):
    def test_actual_com_slots_faces_unbind_and_invalid_index(self):
        code = r'''
#define main shared_backend_main
#include "backend_com_sm3.c"
#undef main
static unsigned slot_zero_calls;
void metal_set_render_target(unsigned target){slot_zero_calls++;observed_targets[0]=target;}
void metal_register_ps(int id,const char*source){assert(id>0&&source&&*source);}
void metal_set_ps_model(int id,unsigned version,const int types[16]){(void)id;(void)version;(void)types;}
void metal_set_blend(unsigned key,float alpha){(void)alpha;observed_color_write[0]=(key>>14)&15;}
void metal_set_blendcolor(uint32_t color){(void)color;}
void metal_set_fog(unsigned enabled,unsigned color){(void)enabled;(void)color;}
void metal_set_depth(unsigned mode){(void)mode;}
int main(void){
 g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
 mem_commit(0x10000,0x10000);CPU cpu={0};uint32_t device=com_new(IF_DEV,16),args[8]={0};
 cpu.ebx=11;cpu.ecx=22;cpu.edx=33;cpu.esi=44;cpu.edi=55;cpu.ebp=66;cpu.eip=77;
 cpu.cf=1;cpu.zf=0;cpu.fcw=0x27f;cpu.top=3;cpu.st[3]=1.25;CPU before=cpu;
 uint32_t surfaces[4];metal_on=1;
 for(unsigned slot=0;slot<4;slot++){
  uint32_t surface=com_new(IF_SURF,64);surfaces[slot]=surface;
  MR32(surface+4)=64;MR32(surface+8)=64;MR32(surface+28)=10+slot;
  MR32(surface+44)=slot?slot+1:0;
  unsigned refs=CH_REF(surface);args[0]=slot;args[1]=surface;
  assert(!invoke(&cpu,IF_DEV,"SetRenderTarget",device,args));
  assert(g_bind_rt[slot]==surface&&CH_REF(surface)==refs+1);
  assert(observed_targets[slot]==((10+slot)|((slot?slot+1:0)<<16)));
  assert(g_cur_rt==10&&slot_zero_calls==1);
  CPU expected=before;expected.esp=cpu.esp;expected.eax=0;expected.eip=0x1234;
  assert(!memcmp(&cpu,&expected,sizeof cpu));
  args[1]=0x18000;assert(!invoke(&cpu,IF_DEV,"GetRenderTarget",device,args));
  assert(MR32(0x18000)==surface&&CH_REF(surface)==refs+2);
  invoke(&cpu,IF_SURF,"Release",surface,args);
 }
 assert(observed_target_calls==3);
 for(unsigned slot=1;slot<4;slot++){
  unsigned refs=CH_REF(surfaces[slot]);args[0]=slot;args[1]=0;
  assert(!invoke(&cpu,IF_DEV,"SetRenderTarget",device,args));
  assert(!g_bind_rt[slot]&&!observed_targets[slot]&&CH_REF(surfaces[slot])==refs-1);
  assert(g_cur_rt==10&&g_bind_rt[0]==surfaces[0]&&slot_zero_calls==1);
 }
 assert(observed_target_calls==6);
 args[0]=4;args[1]=surfaces[1];unsigned refs=CH_REF(surfaces[1]);
 assert(invoke(&cpu,IF_DEV,"SetRenderTarget",device,args)==0x8876086cu);
 assert(CH_REF(surfaces[1])==refs&&observed_target_calls==6&&slot_zero_calls==1);
 assert(g_bind_rt[0]==surfaces[0]&&!g_bind_rt[1]&&!g_bind_rt[2]&&!g_bind_rt[3]);
 const uint32_t program[]={0xffff0200,0x02000001,0x800f0800,0xa0e40000,
                          0x02000001,0x800f0801,0xa0e40001,0x0000ffff};
 memcpy(g_mem+0x19000,program,sizeof program);args[0]=0x19000;args[1]=0x18000;
 assert(!invoke(&cpu,IF_DEV,"CreatePixelShader",device,args));
 unsigned id=MR32(MR32(0x18000)+12);assert(id&&observed_ps_outputs[id]==3);
 assert(observed_ps_outputs[id+PSCUBE]==3);
 /* D3D defaults are all channels, including the secondary attachments. */
 for(unsigned slot=1;slot<4;slot++){
  args[0]=189+slot;args[1]=0x18000;
  assert(!invoke(&cpu,IF_DEV,"GetRenderState",device,args)&&MR32(0x18000)==15);
 }
 unsigned states[]={168,190,191,192},masks[]={0,1,2,8};
 for(unsigned slot=0;slot<4;slot++){
  args[0]=states[slot];args[1]=masks[slot];assert(!invoke(&cpu,IF_DEV,"SetRenderState",device,args));
 }
 assert(!memcmp(observed_color_write,masks,sizeof masks)&&observed_color_write_calls>=3);
 args[0]=2;args[1]=0x18000;assert(!invoke(&cpu,IF_DEV,"CreateStateBlock",device,args));
 uint32_t block=MR32(0x18000);
 for(unsigned slot=0;slot<4;slot++){
  args[0]=states[slot];args[1]=15;assert(!invoke(&cpu,IF_DEV,"SetRenderState",device,args));
 }
 assert(!invoke(&cpu,IF_STATEBLOCK,"Apply",block,args));
 assert(!memcmp(observed_color_write,masks,sizeof masks));
 invoke(&cpu,IF_STATEBLOCK,"Release",block,args);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'test.c'
            binary = Path(temporary) / 'test'
            source.write_text(code)
            flags = ['-O1', '-I' + str(ROOT / 'runtime'), '-I' + str(ROOT / 'tests'),
                     '-Wl,-undefined,dynamic_lookup']
            if os.environ.get('NFSMW_MRT_SANITIZE') == '1':
                flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            built = subprocess.run(['clang', *flags, str(source), str(ROOT / 'runtime/vsemu.c'),
                                    '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            for mode in ('standard', 'full'):
                run = subprocess.run([str(binary)], env={**os.environ, 'NFSMW_MODE': mode},
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
