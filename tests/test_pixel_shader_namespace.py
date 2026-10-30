"""COM pixel shader IDs stay disjoint from cube and reflection variants."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires native COM fixture')
class PixelShaderNamespaceTests(unittest.TestCase):
    def test_creation_ranges_metadata_and_exhaustion(self):
        prefix = (ROOT / 'tests/backend_com_sm3.c').read_text().split('static void rain_fvf(')[0]
        prefix = prefix.replace('#include "../runtime/com.c"',
                                '#include "' + str(ROOT / 'runtime/com.c') + '"')
        body = r'''
static char *registered[10240];
static unsigned registration_calls,model_calls;
static unsigned models[10240];static int sampler_types[10240][16];
void metal_register_ps(int id,const char*source){
 assert(id>0&&id<10240&&source&&*source);registration_calls++;
 /* Match Metal's first-registration ownership; a collision retains wrong code. */
 if(!registered[id])registered[id]=strdup(source);
}
void metal_set_ps_model(int id,unsigned model,const int types[16]){
 assert(id>0&&id<10240);models[id]=model;memcpy(sampler_types[id],types,sizeof sampler_types[id]);model_calls++;
}
static uint32_t create(CPU*c,uint32_t device,unsigned model,unsigned mask){
 uint32_t code[16]={model,0x02000001,0x800f0800,0xa0e40000,0xffff};unsigned n=5;
 if(mask==3){code[4]=0x02000001;code[5]=0x800f0801;code[6]=0xa0e40001;code[7]=0xffff;n=8;}
 if(model==0xffff0101u){const uint32_t legacy[]={0xffff0101,0x42,0xb00f0003,0x1,0x800f0000,0xb0e40003,0xffff};memcpy(code,legacy,sizeof legacy);n=7;}
 /* Distinct bytecode must consume IDs even when the shader bodies match. */
 memmove(code+3,code+1,(n-1)*4);code[1]=0x0001fffe;code[2]=(uint32_t)g_psn+1;n+=2;
 memcpy(g_mem+0x18000,code,n*4);MR32(0x18100)=0xdeadbeef;
 uint32_t a[8]={0x18000,0x18100};uint32_t result=invoke(c,IF_DEV,"CreatePixelShader",device,a);
 if(result){assert(!MR32(0x18100));return result;}
 uint32_t object=MR32(0x18100);assert(object);return MR32(object+12);
}
int main(void){
 g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
 mem_commit(0x10000,0x10000);CPU c={0};uint32_t device=com_new(IF_DEV,16);
 for(unsigned id=1;id<1024;id++){
  unsigned model=id==258?0xffff0300u:id==1023?0xffff0101u:0xffff0200u,mask=id==258?3:1;
  assert(create(&c,device,model,mask)==id);
  assert(registered[id]&&models[id]==(model&0xffffu)&&observed_ps_outputs[id]==mask);
  if(id==258){assert(strstr(registered[id],"PSMRT_258"));assert(!strstr(registered[id],"texturecube<float> s0"));}
  else{assert(registered[id+1024]);assert(models[id+1024]==(model&0xffffu)&&sampler_types[id+1024][0]==3&&observed_ps_outputs[id+1024]==mask);}
  if(id==320){
   assert(registered[258]&&registered[1026]&&strcmp(registered[258],registered[1026]));
   assert(strstr(registered[258],"PSMRT_258")&&strstr(registered[1026],"texturecube<float> s0"));
   assert(registration_calls==639&&model_calls==639);
  }
 }
 assert(g_psn==1023&&registered[1023]&&registered[2047]);
 unsigned old_registrations=registration_calls,old_models=model_calls;
 uint64_t old_live=g_com_live,old_objects=g_com_new_n[IF_VSHADER],old_bytes=g_com_bytes;
 uint32_t old_com_ptr=com_ptr,old_gbuf_ptr=gbuf_ptr;
 unsigned old_masks[10240];memcpy(old_masks,observed_ps_outputs,sizeof old_masks);
 for(unsigned i=0;i<3;i++){
  assert(create(&c,device,0xffff0200,1)==0x8007000eu);
  assert(g_psn==1023&&registration_calls==old_registrations&&model_calls==old_models);
  assert(g_com_live==old_live&&g_com_new_n[IF_VSHADER]==old_objects&&g_com_bytes==old_bytes);
  assert(com_ptr==old_com_ptr&&gbuf_ptr==old_gbuf_ptr);
  assert(!memcmp(old_masks,observed_ps_outputs,sizeof old_masks));
 }
 /* Exhausting pixel IDs must not prevent independent vertex shader creation. */
 const uint32_t vertex[]={0xfffe0200,0x02000001,0xc00f0000,0x90e40000,0xffff};
 memcpy(g_mem+0x18000,vertex,sizeof vertex);uint32_t a[8]={0x18000,0x18100};
 assert(!invoke(&c,IF_DEV,"CreateVertexShader",device,a)&&MR32(0x18100));
#if NFS_ENHANCED
 assert(com_ps_refl_variant(1023,1,3,10239));assert(registered[10239]&&observed_ps_outputs[10239]==1);
 old_registrations=registration_calls;assert(!com_ps_refl_variant(1024,0,0,3072));assert(registration_calls==old_registrations);
#endif
 for(unsigned i=0;i<10240;i++)free(registered[i]);return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'test.c';binary = Path(temporary) / 'test'
            source.write_text(prefix + body)
            for enhanced in (0, 1):
                flags = ['-O1', '-DNFS_ENHANCED=' + str(enhanced),
                         '-I' + str(ROOT / 'runtime'), '-Wl,-undefined,dynamic_lookup']
                if os.environ.get('NFSMW_PS_NAMESPACE_SANITIZE') == '1':
                    flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
                result = subprocess.run(['clang', *flags, str(source), str(ROOT / 'runtime/vsemu.c'),
                                         '-o', str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for mode in ('standard', 'full'):
                    result = subprocess.run([str(binary)], env={**os.environ, 'NFSMW_MODE': mode},
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
