"""GPU shader reuse follows fetched inputs, independent of declaration handles."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'Native COM fixture requires macOS')
class GPUVertexCacheTests(unittest.TestCase):
    def test_fresh_declarations_reuse_layout_and_keep_programs_distinct(self):
        prefix = (ROOT / 'tests/backend_com_sm3.c').read_text().split('static void rain_fvf(')[0]
        prefix = prefix.replace('#include "../runtime/com.c"',
                                '#include "' + str(ROOT / 'runtime/com.c') + '"')
        prefix = prefix.replace('void metal_set_texproj(const float p[4]){(void)p;}',
                                'static float observed_proj[4];\n'
                                'void metal_set_texproj(const float p[4]){memcpy(observed_proj,p,sizeof observed_proj);}')
        body = r'''
static unsigned registrations,raw_draws,last_stride;static int last_gid;
static char registered_source[16][65536];
void metal_register_vs(int gid,const char *source){
 assert(gid>0&&gid<16&&strlen(source)<sizeof registered_source[gid]);
 strcpy(registered_source[gid],source);registrations++;
}
int metal_vs_ready(int gid){return gid>0&&gid<16&&registered_source[gid][0];}
int metal_draw_raw(const void *data,unsigned count,unsigned stride,unsigned primitive,
 unsigned texture,int gid,const float *constants,unsigned nconstants){
 (void)data;(void)texture;(void)constants;(void)nconstants;
 assert(count==3&&primitive==4);raw_draws++;last_gid=gid;last_stride=stride;return 1;
}
float ws_persp_x(void){return 1;}float ws_persp_y(void){return 1;}
float ws_ui_x(void){return 1;}float ws_ui_y(void){return 1;}
int ws_fill_target(void){return 0;}int ws_take_border_quad(void){return 0;}
void metal_tex_size(unsigned texture,unsigned*w,unsigned*h){(void)texture;if(w)*w=1920;if(h)*h=1080;}
int metal_tex_is_cube(unsigned texture){(void)texture;return 0;}
static uint32_t declaration(CPU*c,uint32_t device,unsigned offset,unsigned type,int reverse,int extra){
 uint32_t p=0x18000;unsigned count=extra?3:2;memset(g_mem+p,0,32);
 unsigned pi=reverse?1:0,ti=reverse?0:1;
 MR16(p+pi*8+2)=offset;MR8(p+pi*8+4)=type;MR8(p+pi*8+6)=0;
 MR16(p+ti*8+2)=16;MR8(p+ti*8+4)=1;MR8(p+ti*8+6)=5;
 if(extra){MR16(p+18)=24;MR8(p+20)=2;MR8(p+22)=3;}
 MR16(p+count*8)=0xff;MR8(p+count*8+4)=17;
 uint32_t a[8]={p,0x18100};assert(!invoke(c,IF_DEV,"CreateVertexDeclaration",device,a));
 uint32_t handle=MR32(0x18100);assert(handle);a[0]=handle;
 assert(!invoke(c,IF_DEV,"SetVertexDeclaration",device,a));return handle;
}
static int draw(unsigned stride){assert(draw_up(4,3,0x19000,stride));return last_gid;}
int main(void){
 g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
 mem_commit(0x10000,0x10000);CPU c={0};uint32_t device=com_new(IF_DEV,16),a[8]={0};
 const uint32_t code[]={0xfffe0200,0x0200001f,0x80000000,0x900f0000,
  0x0200001f,0x80000005,0x900f0001,0x02000001,0xc00f0000,0x90e40000,
  0x02000001,0xe00f0000,0x90e40001,0x0000ffff};
 memcpy(g_mem+0x18200,code,sizeof code);a[0]=0x18200;a[1]=0x18300;
 assert(!invoke(&c,IF_DEV,"CreateVertexShader",device,a));uint32_t shader=MR32(0x18300);
 a[0]=shader;assert(!invoke(&c,IF_DEV,"SetVertexShader",device,a));
 float vertices[3][8]={{-.5,.5,.2,1,.1,.2,0,0},{.5,.5,.2,1,.3,.2,0,0},{-.5,-.5,.2,1,.1,.4,0,0}};
 memcpy(g_mem+0x19000,vertices,sizeof vertices);g_gpuvs=1;
 int first=0;uint32_t previous=0;
 for(unsigned i=0;i<600;i++){
  uint32_t handle=declaration(&c,device,0,2,i&1,i%3==0);assert(handle!=previous);previous=handle;
  g_tss_raw[0][11]=i&1;g_tss_raw[0][24]=i&1?0x103:0;
  int gid=draw(i&1?32:40);if(!first)first=gid;
  assert(gid==first&&registrations==1&&g_gpuvs_fail==0);
  assert(last_stride==(i&1?32u:40u));
  assert(observed_proj[0]==(i&1?17.f:0.f));
  assert(invoke(&c,IF_VDECL,"Release",handle,a)==0); /* retained lifetime stays unchanged */
 }
 assert(raw_draws==600&&g_gvsn==1&&g_gvs_next==2);
 declaration(&c,device,4,2,0,0);int moved=draw(32);assert(moved!=first&&registrations==2);
 assert(strstr(registered_source[first],"LDF(0)")&&strstr(registered_source[moved],"LDF(4)"));
 declaration(&c,device,0,3,0,0);int typed=draw(32);assert(typed!=first&&typed!=moved&&registrations==3);
 declaration(&c,device,0,2,0,0);assert(draw(32)==first&&registrations==3);
 MR32(0x18200+12*4)=0x90e40000; /* A different program must retain its own GPU shader. */
 a[0]=0x18200;a[1]=0x18300;assert(!invoke(&c,IF_DEV,"CreateVertexShader",device,a));
 uint32_t other=MR32(0x18300);assert(other!=shader);a[0]=other;
 assert(!invoke(&c,IF_DEV,"SetVertexShader",device,a));int program=draw(32);
 assert(program!=first&&program!=moved&&program!=typed&&registrations==4);
 a[0]=shader;assert(!invoke(&c,IF_DEV,"SetVertexShader",device,a));assert(draw(40)==first);
 assert(g_gvsn==4&&g_gvs_next==5&&g_gpuvs_fail==0&&raw_draws==605);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'test.c'
            binary = Path(temporary) / 'test'
            source.write_text(prefix + body)
            flags = ['-O1', '-I' + str(ROOT / 'runtime'), '-Wl,-undefined,dynamic_lookup']
            if os.environ.get('NFSMW_GPU_CACHE_SANITIZE') == '1':
                flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            compiled = subprocess.run(['clang', *flags, str(source), str(ROOT / 'runtime/vsemu.c'),
                                       '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            for mode in ('standard', 'full'):
                ran = subprocess.run([str(binary)], env={**os.environ, 'NFSMW_MODE': mode},
                                     capture_output=True, text=True)
                self.assertEqual(ran.returncode, 0, ran.stderr)


if __name__ == '__main__':
    unittest.main()
