"""COM texture locks propagate readback failures and honor readonly access."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires native COM fixture')
class TextureReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temporary.name) / 'test'
        source = Path(cls.temporary.name) / 'test.c'
        prefix = (ROOT / 'tests/backend_com_sm3.c').read_text().split('static void rain_fvf(')[0]
        prefix = prefix.replace('#include "../runtime/com.c"',
                                '#include "' + str(ROOT / 'runtime/com.c') + '"')
        code = r'''
static unsigned reads,uploads,replacements,invalidations,read_id;
static int read_ok=1;
int metal_read_texture(unsigned id,void*dst,unsigned pitch,unsigned rows){
 reads++;read_id=id;assert(pitch==452&&rows==64);
 if(!read_ok)return 0;
 memset(dst,64,pitch*rows);return 1;
}
void metal_upload_texture(unsigned id,unsigned level,const void*data,unsigned pitch,
                          unsigned w,unsigned h,unsigned fmt){
 (void)id;(void)level;(void)data;(void)pitch;(void)w;(void)h;(void)fmt;uploads++;
}
void metal_free_texture(unsigned id){(void)id;}
void texrep_uploaded(unsigned id,unsigned level,const uint8_t*d,unsigned pitch,unsigned rows){
 (void)id;(void)level;(void)d;(void)pitch;(void)rows;replacements++;
}
void texrep_surface_written(unsigned id){(void)id;invalidations++;}
static uint32_t checked(CPU*c,int type,const char*method,uint32_t self,uint32_t*a){
 c->ebx=0x12345678;c->ebp=0x23456789;c->esi=0x3456789a;c->edi=0x456789ab;
 uint32_t result;
 if(type==IF_TEX&&is_cube_tex(self)&&(!strcmp(method,"GetSurfaceLevel")||!strcmp(method,"LockRect")||!strcmp(method,"UnlockRect"))){
  unsigned slot=0;while(slot<g_if[type].n&&strcmp(g_if[type].m[slot].name,method))slot++;
  assert(slot<g_if[type].n);
  unsigned nargs=!strcmp(method,"LockRect")?6:!strcmp(method,"UnlockRect")?3:4;
  c->esp=0x10000;MR32(c->esp)=0x1234;MR32(c->esp+4)=self;
  for(unsigned i=1;i<nargs;i++)MR32(c->esp+4+i*4)=a[i-1];
  assert(com_call(c,COM_MAGIC|(type<<16)|slot));assert(c->esp==0x10004+nargs*4);result=c->eax;
 }else result=invoke(c,type,method,self,a);
 assert(c->ebx==0x12345678&&c->ebp==0x23456789&&c->esi==0x3456789a&&c->edi==0x456789ab);
 return result;
}
static uint32_t texture(unsigned cube){
 uint32_t t=com_new(IF_TEX,TEX_EXTRA);MR32(t+4)=16;MR32(t+8)=16;
 MR32(t+20)=21;MR32(t+24)=4;MR32(t+28)=99;if(cube)cube_mark(t);return t;
}
static uint32_t child(CPU*c,uint32_t t,unsigned cube,unsigned face,unsigned level){
 uint32_t a[8]={cube?face:level,cube?level:0x18000,0x18000};
 assert(!checked(c,IF_TEX,"GetSurfaceLevel",t,a));return MR32(0x18000);
}
static void surface_failure(CPU*c){
 uint32_t sf=com_new(IF_SURF,64),a[8]={0x18000,0,0x10};
 MR32(sf+4)=113;MR32(sf+8)=64;MR32(sf+20)=21;MR32(sf+28)=17;MR32(sf+40)=3;
 MR32(0x17ffc)=0xaabbccdd;MR32(0x18008)=0x11223344;
 MR32(0x18000)=0xdeadbeef;MR32(0x18004)=0xdeadbeef;read_ok=0;
 assert(checked(c,IF_SURF,"LockRect",sf,a)==0x8876086cu);
 assert(!MR32(0x18000)&&!MR32(0x18004)&&reads==1&&read_id==17);
 assert(MR32(0x17ffc)==0xaabbccdd&&MR32(0x18008)==0x11223344);
 assert(checked(c,IF_SURF,"UnlockRect",sf,a)==0x8876086cu&&!uploads);
 read_ok=1;assert(!checked(c,IF_SURF,"LockRect",sf,a));
 assert(MR32(0x18000)==452&&MR8(MR32(0x18004))==64&&reads==2);
 assert(!checked(c,IF_SURF,"UnlockRect",sf,a));assert(!uploads&&!invalidations);
 uint32_t backing=MR32(0x18004);MR8(backing)=77;read_ok=0;
 assert(checked(c,IF_SURF,"LockRect",sf,a)==0x8876086cu);
 assert(!MR32(0x18000)&&!MR32(0x18004)&&MR8(backing)==77);
 assert(checked(c,IF_SURF,"UnlockRect",sf,a)==0x8876086cu);
 assert(!checked(c,IF_SURF,"Release",sf,a));
}
static void readonly_surface(CPU*c){
 uint32_t sf=com_new(IF_SURF,64),a[8]={0x18000,0,0x10};
 MR32(sf+4)=113;MR32(sf+8)=64;MR32(sf+20)=21;MR32(sf+28)=17;MR32(sf+40)=3;
 assert(!checked(c,IF_SURF,"LockRect",sf,a));MR8(MR32(0x18004))=255;
 assert(!checked(c,IF_SURF,"UnlockRect",sf,a));assert(!uploads&&!invalidations);
 a[2]=0;assert(!checked(c,IF_SURF,"LockRect",sf,a));assert(!checked(c,IF_SURF,"UnlockRect",sf,a));
 assert(uploads==1&&invalidations==1&&reads==2);
 assert(!checked(c,IF_SURF,"Release",sf,a));
}
static void subresources(CPU*c){
 uint32_t a[8]={0,0x18000,0,0x10},t=texture(0),sf=child(c,t,0,0,2);
 assert(!checked(c,IF_TEX,"LockRect",t,a));
 a[0]=1;a[3]=0;assert(!checked(c,IF_TEX,"LockRect",t,a));
 a[0]=0x18000;a[1]=0;a[2]=0x10;assert(!checked(c,IF_SURF,"LockRect",sf,a));
 a[0]=1;assert(!checked(c,IF_TEX,"UnlockRect",t,a));assert(uploads==1&&replacements==1);
 a[0]=2;assert(!checked(c,IF_TEX,"UnlockRect",t,a));assert(uploads==1&&replacements==1&&!invalidations);
 a[0]=0;assert(!checked(c,IF_TEX,"UnlockRect",t,a));assert(uploads==1&&replacements==1);
 /* A texture lock can also be unlocked through its surface alias. */
 a[0]=2;a[1]=0x18000;a[2]=0;a[3]=0x10;assert(!checked(c,IF_TEX,"LockRect",t,a));
 assert(!checked(c,IF_SURF,"UnlockRect",sf,a));assert(uploads==1&&!invalidations);
 /* Writable alias uploads keep their previous behavior. */
 a[0]=0x18000;a[1]=0;a[2]=0;assert(!checked(c,IF_SURF,"LockRect",sf,a));
 assert(!checked(c,IF_SURF,"UnlockRect",sf,a));assert(uploads==2&&invalidations==1);
 assert(checked(c,IF_SURF,"Release",sf,a)>0);assert(!checked(c,IF_TEX,"Release",t,a));
 uint32_t cube=texture(1);sf=child(c,cube,1,4,1);
 a[0]=0;a[1]=0;a[2]=0x18000;a[3]=0;a[4]=0x10;assert(!checked(c,IF_TEX,"LockRect",cube,a));
 a[0]=1;a[4]=0;assert(!checked(c,IF_TEX,"LockRect",cube,a));
 a[0]=0;a[1]=1;a[4]=0;assert(!checked(c,IF_TEX,"LockRect",cube,a));
 a[0]=0x18000;a[1]=0;a[2]=0x10;assert(!checked(c,IF_SURF,"LockRect",sf,a));
 unsigned before=uploads;
 a[0]=1;a[1]=0;assert(!checked(c,IF_TEX,"UnlockRect",cube,a));assert(uploads==before+1);
 a[0]=0;a[1]=1;assert(!checked(c,IF_TEX,"UnlockRect",cube,a));assert(uploads==before+2);
 a[0]=0;a[1]=0;assert(!checked(c,IF_TEX,"UnlockRect",cube,a));assert(uploads==before+2);
 a[0]=4;a[1]=1;assert(!checked(c,IF_TEX,"UnlockRect",cube,a));assert(uploads==before+2);
 assert(checked(c,IF_SURF,"Release",sf,a)>0);assert(!checked(c,IF_TEX,"Release",cube,a));
 assert(!reads);
}
int main(int argc,char**argv){
 assert(argc==2);g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
 assert(g_mem!=MAP_FAILED);mem_commit(0x10000,0x10000);CPU c={0};metal_on=1;
 if(!strcmp(argv[1],"failure"))surface_failure(&c);
 else if(!strcmp(argv[1],"readonly"))readonly_surface(&c);
 else if(!strcmp(argv[1],"subresources"))subresources(&c);
 else return 2;
 return 0;
}
'''
        source.write_text(prefix + code)
        flags = ['-O1', '-I' + str(ROOT / 'runtime'), '-Wl,-undefined,dynamic_lookup']
        if os.environ.get('NFSMW_READBACK_SANITIZE') == '1':
            flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        result = subprocess.run(['clang', *flags, str(source), str(ROOT / 'runtime/vsemu.c'),
                                 '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case):
        for mode in ('standard', 'full'):
            result = subprocess.run([str(self.binary), case],
                                    env={**os.environ, 'NFSMW_MODE': mode},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_surface_readback_is_not_a_successful_lock(self):
        self.run_case('failure')

    def test_readonly_surface_unlock_preserves_gpu_image(self):
        self.run_case('readonly')

    def test_flags_follow_levels_faces_and_surface_aliases(self):
        self.run_case('subresources')


if __name__ == '__main__':
    unittest.main()
