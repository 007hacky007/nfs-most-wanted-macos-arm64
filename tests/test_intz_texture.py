"""INTZ texture/surface aliases own one depth image and one reserved depth ID."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires native COM fixture')
class INTZTextureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        directory = Path(cls.temporary.name)
        prefix = (ROOT / 'tests/backend_com_sm3.c').read_text().split('static void rain_fvf(')[0]
        prefix = prefix.replace('#include "../runtime/com.c"',
                                '#include "' + str(ROOT / 'runtime/com.c') + '"')
        body = r'''
#define INTZ 0x5a544e49u
static unsigned depth_calls,color_calls,frees,resets,z_current,z_forgot,next_image=42;
static int allocation_ok=1;
unsigned metal_create_depth_texture(unsigned w,unsigned h,unsigned zid){
 assert(w==1024&&h==768&&zid>=2&&zid<64);depth_calls++;
 return allocation_ok?next_image++:0;
}
unsigned metal_create_texture_ex(unsigned w,unsigned h,unsigned levels,unsigned format,unsigned rt){
 (void)w;(void)h;(void)levels;(void)rt;color_calls++;assert(format!=INTZ);return next_image++;
}
void metal_free_texture(unsigned id){assert(id>=42&&id<next_image);frees++;}
void metal_z_forget(unsigned id){z_forgot=id;}
void metal_set_zsurf(unsigned id){z_current=id;}
void metal_reset_rts(void){resets++;}
void metal_query_reset(void){}
void metal_set_render_target(unsigned target){observed_targets[0]=target;observed_target_calls++;}
static uint32_t create(CPU*c,uint32_t device){
 uint32_t a[9]={1024,768,1,2,INTZ,0,0x18000,0};MR32(0x18000)=0xdeadbeef;
 assert(!invoke(c,IF_DEV,"CreateTexture",device,a));uint32_t t=MR32(0x18000);assert(t);return t;
}
static uint32_t surface(CPU*c,uint32_t texture){
 uint32_t a[8]={0,0x18004};assert(!invoke(c,IF_TEX,"GetSurfaceLevel",texture,a));assert(MR32(0x18004));return MR32(0x18004);
}
static void invalid(CPU*c,uint32_t device){
 const uint32_t cases[][7]={{0,768,1,2,INTZ,0,0x18000},{8193,768,1,2,INTZ,0,0x18000},
 {1024,0,1,2,INTZ,0,0x18000},{1024,8193,1,2,INTZ,0,0x18000},
 {1024,768,0,2,INTZ,0,0x18000},{1024,768,2,2,INTZ,0,0x18000},
 {1024,768,1,0,INTZ,0,0x18000},{1024,768,1,1,INTZ,0,0x18000},
 {1024,768,1,3,INTZ,0,0x18000},{1024,768,1,2,INTZ,1,0x18000},
 {1024,768,1,2,INTZ,0,0}};
 uint64_t live=g_com_live,objects=g_com_new_n[IF_TEX];unsigned calls=depth_calls;
 for(unsigned i=0;i<sizeof cases/sizeof cases[0];i++){
  uint32_t a[9]={0};memcpy(a,cases[i],sizeof cases[i]);MR32(0x18000)=0xdeadbeef;
  assert(invoke(c,IF_DEV,"CreateTexture",device,a)==0x8876086cu);
  if(a[6])assert(!MR32(a[6]));assert(g_com_live==live&&g_com_new_n[IF_TEX]==objects&&depth_calls==calls&&!color_calls);
 }
 allocation_ok=0;uint32_t a[9]={1024,768,1,2,INTZ,0,0x18000,0};
 for(unsigned i=0;i<70;i++){MR32(0x18000)=0xdeadbeef;assert(invoke(c,IF_DEV,"CreateTexture",device,a)==0x8007000eu);assert(!MR32(0x18000)&&g_com_live==live);}
 assert(depth_calls==calls+70&&!color_calls&&!frees);allocation_ok=1;
 uint32_t t=create(c,device),sf=surface(c,t);a[0]=0x18008;assert(!invoke(c,IF_SURF,"GetDesc",sf,a));
 assert(MR32(0x18008)==INTZ&&MR32(0x18010)==2&&MR32(0x18014)==0&&MR32(0x18020)==1024&&MR32(0x18024)==768);
 a[0]=1;a[1]=0x18008;MR32(0x18008)=0xdeadbeef;
 assert(invoke(c,IF_TEX,"GetSurfaceLevel",t,a)==0x8876086cu&&!MR32(0x18008));
 a[0]=sf;assert(invoke(c,IF_SURF,"Release",sf,a)==1);assert(!invoke(c,IF_TEX,"Release",t,a));assert(frees==1);
}
static void aliases(CPU*c,uint32_t device){
 uint32_t t=create(c,device),sf=surface(c,t),a[9]={0};unsigned image=MR32(t+28);assert(image==42&&MR32(sf+28)==42);
 a[0]=sf;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));unsigned zid=z_current;assert(zid>=2&&zid<64&&g_cur_zid==zid);
 a[0]=0x18008;assert(!invoke(c,IF_DEV,"GetDepthStencilSurface",device,a)&&MR32(0x18008)==sf);
 assert(invoke(c,IF_SURF,"Release",sf,a)>0);
 a[0]=4;a[1]=t;assert(!invoke(c,IF_DEV,"SetTexture",device,a));assert(g_raw_tex[4]==t&&g_tex_stage[4]==42);
 unsigned refs=CH_REF(t),calls=observed_target_calls;uint32_t bump=gbuf_ptr;
 for(unsigned slot=0;slot<4;slot++){a[0]=slot;a[1]=sf;assert(invoke(c,IF_DEV,"SetRenderTarget",device,a)==0x8876086cu);assert(CH_REF(t)==refs&&observed_target_calls==calls&&!g_bind_rt[slot]);}
 a[0]=0;a[1]=0x18008;a[2]=0;a[3]=0x10;MR32(0x18008)=MR32(0x1800c)=0xdeadbeef;
 assert(invoke(c,IF_TEX,"LockRect",t,a)==0x8876086cu&&!MR32(0x18008)&&!MR32(0x1800c)&&gbuf_ptr==bump);
 a[0]=0x18008;a[1]=0;a[2]=0x10;assert(invoke(c,IF_SURF,"LockRect",sf,a)==0x8876086cu&&gbuf_ptr==bump);
 a[0]=1024;a[1]=768;a[2]=INTZ;a[3]=0;a[4]=0;a[5]=0;a[6]=0x18008;a[7]=0;
 assert(invoke(c,IF_DEV,"CreateRenderTarget",device,a)==0x8876086cu&&!MR32(0x18008)&&!color_calls);
 assert(invoke(c,IF_TEX,"Release",t,a)>0);assert(invoke(c,IF_SURF,"Release",sf,a)>0);assert(!frees);
 a[0]=0;assert(!invoke(c,IF_DEV,"Reset",device,a));assert(resets==1&&frees==1&&!com_valid(t)&&!com_valid(sf));
 uint32_t next=create(c,device),nextsf=surface(c,next);a[0]=nextsf;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));assert(z_current!=zid);
 a[0]=0;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));assert(invoke(c,IF_SURF,"Release",nextsf,a)==1);assert(!invoke(c,IF_TEX,"Release",next,a));assert(frees==2);
}
static void capacity(CPU*c,uint32_t device){
 uint32_t textures[62],surfaces[62];unsigned ids[62];uint32_t a[9]={0};
 metal_on=0;
 for(unsigned i=0;i<62;i++){
  textures[i]=create(c,device);surfaces[i]=surface(c,textures[i]);assert(!MR32(textures[i]+28));
  a[0]=surfaces[i];assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));ids[i]=g_cur_zid;
  for(unsigned j=0;j<i;j++)assert(ids[i]!=ids[j]);a[0]=0;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));
 }
 a[0]=1024;a[1]=768;a[2]=1;a[3]=2;a[4]=INTZ;a[5]=0;a[6]=0x18000;a[7]=0;
 uint64_t live=g_com_live;assert(invoke(c,IF_DEV,"CreateTexture",device,a)==0x8007000eu&&!MR32(0x18000)&&g_com_live==live);
 a[0]=1024;a[1]=768;a[2]=75;a[3]=0;a[4]=0;a[5]=0;a[6]=0x18000;a[7]=0;
 assert(invoke(c,IF_DEV,"CreateDepthStencilSurface",device,a)==0x8007000eu&&!MR32(0x18000)&&g_com_live==live);
 for(unsigned i=0;i<62;i++){assert(invoke(c,IF_SURF,"Release",surfaces[i],a)==1);assert(!invoke(c,IF_TEX,"Release",textures[i],a));}
 /* A depth texture's released ID remains protected while queued frames may name it. */
 assert(invoke(c,IF_DEV,"CreateDepthStencilSurface",device,a)==0x8007000eu&&!MR32(0x18000));
 g_present_no+=3;uint32_t t=create(c,device),sf=surface(c,t);a[0]=sf;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));
 unsigned reused=g_cur_zid;int found=0;for(unsigned i=0;i<62;i++)if(ids[i]==reused)found=1;assert(found);
 a[0]=0;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));assert(invoke(c,IF_SURF,"Release",sf,a)==1);assert(!invoke(c,IF_TEX,"Release",t,a));assert(!depth_calls&&!color_calls&&!frees);
}
static void shared_legacy(CPU*c,uint32_t device){
 metal_on=0;uint32_t old[63],a[9]={1024,768,75,0,0,0,0x18000,0};
 for(unsigned i=0;i<63;i++){assert(!invoke(c,IF_DEV,"CreateDepthStencilSurface",device,a));old[i]=MR32(0x18000);assert(old[i]);}
 assert(MR32(old[0]+52)==MR32(old[62]+52));
 assert(!invoke(c,IF_SURF,"Release",old[0],a));g_present_no+=3;
 a[0]=1024;a[1]=768;a[2]=1;a[3]=2;a[4]=INTZ;a[5]=0;a[6]=0x18000;a[7]=0;
 assert(invoke(c,IF_DEV,"CreateTexture",device,a)==0x8007000eu&&!MR32(0x18000));
 assert(!invoke(c,IF_SURF,"Release",old[62],a));g_present_no+=3;
 uint32_t t=create(c,device),sf=surface(c,t);a[0]=sf;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));
 a[0]=0;assert(!invoke(c,IF_DEV,"SetDepthStencilSurface",device,a));assert(invoke(c,IF_SURF,"Release",sf,a)==1);assert(!invoke(c,IF_TEX,"Release",t,a));
 for(unsigned i=1;i<62;i++)assert(!invoke(c,IF_SURF,"Release",old[i],a));
}
int main(int argc,char**argv){
 assert(argc==2);g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);mem_commit(0x10000,0x10000);CPU c={0};uint32_t device=com_new(IF_DEV,16);metal_on=1;
 if(!strcmp(argv[1],"invalid"))invalid(&c,device);else if(!strcmp(argv[1],"aliases"))aliases(&c,device);else if(!strcmp(argv[1],"capacity"))capacity(&c,device);else if(!strcmp(argv[1],"shared"))shared_legacy(&c,device);else return 2;return 0;
}
'''
        source = directory / 'test.c';source.write_text(prefix + body)
        cls.binaries = []
        for enhanced in (0, 1):
            binary = directory / ('test-' + str(enhanced))
            flags = ['-O1', '-DNFS_ENHANCED=' + str(enhanced), '-I' + str(ROOT / 'runtime'),
                     '-Wl,-undefined,dynamic_lookup']
            if os.environ.get('NFSMW_INTZ_SANITIZE') == '1':
                flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            result = subprocess.run(['clang', *flags, str(source), str(ROOT / 'runtime/vsemu.c'),
                                     '-o', str(binary)], capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.binaries.append(binary)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, name):
        for binary in self.binaries:
            for mode in ('standard', 'full'):
                result = subprocess.run([str(binary), name],
                                        env={**os.environ, 'NFSMW_MODE': mode, 'NORSRESET': '1'},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_validation_and_gpu_allocation_failure(self):
        self.run_case('invalid')

    def test_shared_depth_binding_readonly_rejection_and_reset_lifetime(self):
        self.run_case('aliases')

    def test_headless_depth_ids_do_not_alias_or_reuse_queued_images(self):
        self.run_case('capacity')

    def test_legacy_shared_surface_still_owns_its_depth_id(self):
        self.run_case('shared')


if __name__ == '__main__':
    unittest.main()
