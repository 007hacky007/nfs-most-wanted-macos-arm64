from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest


HARNESS = r'''
#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;static float aspect;static int calls,absent;
static CPU expected;
float ws_aspect_ratio(void){return aspect;}
uint32_t gheap_alloc(int heap,uint32_t size,int zero){assert(heap==1&&size==8&&zero);return 0x6000;}
uint32_t call_guest(CPU *c,uint32_t fn,int count,const uint32_t *args){
 assert(!memcmp(c,&expected,sizeof *c));calls++;uint32_t result=0;
 if(fn==0x524850){
  assert(count==2&&args[0]==0x2000);
  if(args[1]==0x1603009e)result=absent?0:0x3000;
  else {assert(args[1]==0x5d0101f1);result=absent?0:0x4000;}
 }else if(fn==0x524ee0){
  assert(count==3);MR32(args[1])=MR32(args[0]);MR32(args[2])=MR32(args[0]+4);
 }else{
  assert(fn==0x525050&&count==3);MR32(args[0])=args[1];MR32(args[0]+4)=args[2];
 }
 memset(c,0xa5,sizeof *c);return result;
}
int mw_hud_adapter_init(int);
int mw_hud_adapter_hook(CPU*,uint32_t);
int mw_hud_adapter_branch(CPU*,uint32_t);
void guest_hook(CPU *c,uint32_t ip){assert(mw_hud_adapter_hook(c,ip));}
int guest_branch(CPU *c,uint32_t ip){int result=mw_hud_adapter_branch(c,ip);assert(result>=0);return result;}
'''


class HUDAdapterTests(unittest.TestCase):
    def run_native(self, body, fragments=''):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'test.c'
            source.write_text(HARNESS+fragments+'\nint main(void){\ng_mem=calloc(1,0x1000000);assert(g_mem);\n'
                              +body+'\nfree(g_mem);return 0;}\n')
            binary=Path(tmp)/'test'
            result=subprocess.run(['clang','-O1','-Iruntime',str(source),
                                   'runtime/mw_hud_adapter.c','-lm','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_group_positions_minimap_and_original_stdcall_stack(self):
        self.run_native(r'''
CPU cpu={0},*c=&cpu;
for(unsigned i=0;i<4;i++){
 const float ratios[]={4.f/3.f,16.f/9.f,21.f/9.f,.75f};aspect=ratios[i];
 assert(mw_hud_adapter_init(1));memset(c,0,sizeof *c);c->esp=0x1000;c->eax=99;c->cf=c->zf=1;c->st[0]=7;
 MR32(0x1004)=0x2000;MRF32(0x3000)=100;MRF32(0x3004)=25;MRF32(0x4000)=200;MRF32(0x4004)=35;
 expected=*c;calls=0;
 assert(mw_hud_adapter_branch(c,i&1?0x569712:0x5696f1)==1);
 volatile float scaled=aspect*240.f;float difference=scaled-320.f;
 assert(calls==6&&MRF32(0x3000)==100-difference&&MRF32(0x4000)==200+difference);
 assert(MRF32(0x3004)==25&&MRF32(0x4004)==35);
 expected.eax=1;expected.esp+=12;assert(!memcmp(c,&expected,sizeof *c));
 assert(mw_hud_adapter_hook(c,0x5678ae)&&c->st[0]==(double)-difference);
 assert(mw_hud_adapter_hook(c,0x5678b8)&&MRF32(0x91cf04)==-difference);
 assert(mw_hud_adapter_hook(c,0x5678ca)&&c->st[0]==(double)difference);
}
absent=1;*c=expected;c->esp=0x1000;expected=*c;calls=0;
assert(mw_hud_adapter_branch(c,0x5696f1)==1&&calls==2);
assert(mw_hud_adapter_init(0));expected=*c;calls=0;
assert(mw_hud_adapter_branch(c,0x5696f1)==0&&!calls&&!memcmp(c,&expected,sizeof *c));
assert(mw_hud_adapter_hook(c,0x5678ae)&&!memcmp(c,&expected,sizeof *c));
assert(mw_hud_adapter_branch(c,0x1234)==-1&&!mw_hud_adapter_hook(c,0x1234));
''')

    @unittest.skipUnless(Path('out/installed/.nfsmw/runtime.exe').is_file(), 'requires supported executable')
    def test_canonical_callback_stack_and_minimap_instructions(self):
        from tools.lift import Lifter
        image=Path('out/installed/.nfsmw/runtime.exe')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        lifter=Lifter(str(image),hooks=[0x5678ae,0x5678b8,0x5678ca],
                      branch_hooks={0x5696f1:0x5696f6,0x569712:0x569717})
        fragments=r'''
static int original_calls;
void sub_00516c90(CPU *c){original_calls++;c->eax=55;c->eip=MR32(c->esp);c->esp+=16;}
'''
        for start,stop in [(0x5696f1,0x5696f6),(0x569712,0x569717),(0x5678a0,0x5678de)]:
            code,_=lifter.lift(start)
            fragment=code[:code.index(f'    /* {stop:08x} ')]
            if f'L_{stop:08x}:' not in fragment:
                fragment+=f'L_{stop:08x}:;\n'
            fragments+=fragment+'}\n'
        self.run_native(r'''
CPU cpu={0},*c=&cpu;aspect=16.f/9.f;
for(unsigned enabled=0;enabled<2;enabled++){
 assert(mw_hud_adapter_init(enabled));
 for(unsigned site=0;site<2;site++){
  memset(c,0,sizeof *c);c->esp=0x1000;MR32(0x1004)=0x2000;expected=*c;
  if(site)sub_00569712(c);else sub_005696f1(c);
  assert(c->esp==0x100c&&c->eax==(enabled?1:55));
 }
 if(enabled){
  volatile float scaled=aspect*240.f;float difference=scaled-320.f;
  for(unsigned left=0;left<2;left++){
   memset(c,0,sizeof *c);c->esp=0x1000;MR32(0x1004)=left;
   sub_005678a0(c);assert(c->top==7&&c->st[7]==(double)(left?-difference:difference));
   assert(MRF32(0x91cf04)==(left?-difference:0));
  }
 }
}
assert(original_calls==2);
''',fragments)


if __name__=='__main__':
    unittest.main()
