from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

HEADER = r'''
#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem;
static const char *config;
static unsigned lookup,render,object=0x5000;
int fileio_resolve_game(const char *name,char *out,size_t size){
 assert(!strcmp(name,"scripts/NFSMWFEShadows.ini"));int n=snprintf(out,size,"%s",config);return n>0&&(size_t)n<size;
}
void sub_007a1fa0(CPU *c){lookup++;c->eax=object;POP32(c->eip);}
void sub_007a2200(CPU *c){render++;assert(c->ecx==object&&MR32(c->esp+4)==4);POP32(c->eip);c->esp+=4;}
int mw_fe_shadows_init(int);
int mw_fe_shadows_hook(CPU*,uint32_t);
int mw_fe_shadows_branch(CPU*,uint32_t);
void guest_hook(CPU *c,uint32_t ip){assert(mw_fe_shadows_hook(c,ip));}
int guest_branch(CPU *c,uint32_t ip){int r=mw_fe_shadows_branch(c,ip);assert(r>=0);return r;}
'''


class FEShadowTests(unittest.TestCase):
    def run_native(self, body, fragments='', configuration=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ini=root/'mod.ini'
            ini.write_text(configuration if configuration is not None else
                '[MAIN]\nRenderWorldShadows=1\nRenderCarShadows=0\nDisableShadowsOnCars=1\nRestoreShadows=0\n')
            source=root/'test.c'
            source.write_text(HEADER+fragments+'\nint main(int argc,char **argv){\n'
                'assert(argc==2);config=argv[1];g_mem=calloc(1,0x1000000);assert(g_mem);\n'
                'CPU cpu={0},*c=&cpu;c->esp=0x8000;c->fcw=0x027f;\n'
                +body+'\nfree(g_mem);return 0;}\n')
            build=subprocess.run(['clang','-O1','-fno-strict-aliasing','-Iruntime',str(source),
                'runtime/mw_fe_shadows.c','-lm','-o',str(root/'test')],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(root/'test'),str(ini)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)

    def test_disabled_and_unsupported_settings(self):
        self.run_native(r'''
assert(mw_fe_shadows_init(0));CPU before=*c;
unsigned sites[]={0x6e518b,0x6e551b,0x6c8323};
for(unsigned i=0;i<3;i++){assert(mw_fe_shadows_hook(c,sites[i]));assert(!memcmp(c,&before,sizeof *c));}
unsigned branches[]={0x74e37f,0x7a22f2,0x6e0b6e};
for(unsigned i=0;i<3;i++){assert(!mw_fe_shadows_branch(c,branches[i]));assert(!memcmp(c,&before,sizeof *c));}
assert(!lookup&&!render);assert(!mw_fe_shadows_hook(c,1));assert(mw_fe_shadows_branch(c,1)==-1);
''')
        for option in ('RenderCarShadows=1','RestoreShadows=1','RenderWorldShadows=','RenderWorldShadows=1junk'):
            self.run_native('assert(!mw_fe_shadows_init(1));',configuration='[MAIN]\nRenderCarShadows=0\n'+option+'\n')

    def test_world_calls_and_particle_view_gate_match_supplied_binary(self):
        self.run_native(r'''
assert(mw_fe_shadows_init(1));MR32(0x982a20)=0x6000;MR32(0x6004)=2;
MR32(0x9195e4+2*0x70)=1;MR32(0x925e90)=3;MR8(0x901830)=1;
mw_fe_shadows_hook(c,0x6e518b);assert(lookup==1&&render==1&&c->esp==0x8000);
object=0;mw_fe_shadows_hook(c,0x6e518b);assert(lookup==2&&render==1);
MR8(0x901830)=0;mw_fe_shadows_hook(c,0x6e518b);assert(lookup==2);
MR8(0x901830)=255;mw_fe_shadows_hook(c,0x6e518b);assert(lookup==2);
MR8(0x901830)=1;MR32(0x925e90)=6;mw_fe_shadows_hook(c,0x6e518b);assert(lookup==2);
c->eax=123;c->ecx=456;c->edi=789;assert(!mw_fe_shadows_branch(c,0x7a22f2));
MR32(0x9195e4+2*0x70)=4;assert(mw_fe_shadows_branch(c,0x7a22f2));
assert(c->eax==123&&c->ecx==456&&c->edi==789&&c->esp==0x8000);
''')

    def test_x360_world_hook_renders_once_and_preserves_its_cpu_result(self):
        from tools.lift import Lifter
        module=Path('out/hq-extract/normalized/LOGIC/41/X360Stuff.asi')
        if not module.is_file():self.skipTest('requires supplied X360 module')
        self.assertEqual(hashlib.sha256(module.read_bytes()).hexdigest(),
                         '0073249a7642a3c1d8bd196c5795cc22da8eb8218349762301ba66b686c00fe8')
        code,_=Lifter(str(module)).lift(0x1000bdb0)
        # Execute the actual frontend path, followed by the zero-scenery path
        # and original cull call. The omitted loop is unreachable in this fixture.
        code=code[:code.index('    /* 1000bde6 ')]+code[code.index('L_1000c01e:'):]
        fragments=r'''
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
static unsigned culled;
void dispatch_indirect(CPU *c,uint32_t target){
 if(target==0x7a1fa0)sub_007a1fa0(c);
 else if(target==0x7a2200)sub_007a2200(c);
 else{
  assert(target==0x723fa0&&c->ecx==0x6000);
  assert(MR32(c->esp+4)==0x11111111&&MR32(c->esp+8)==0x22222222);
  culled++;POP32(c->eip);c->esp+=8;c->eax=0xabcdef;c->cf=1;c->zf=0;
 }
}
'''+code
        self.run_native(r'''
assert(mw_fe_shadows_init(1));MR32(0x925e90)=3;MR8(0x901830)=1;
MR8(0x6e5186)=0xe8;MR32(0x6e5187)=0x0100bdb0u-0x006e518bu;
c->ecx=0x6000;c->edi=0x789abc;c->ebp=0x123456;c->st[0]=1.25;
MR32(0x69c0)=0;MR32(c->esp)=0x6e518b;MR32(c->esp+4)=0x11111111;MR32(c->esp+8)=0x22222222;
sub_1000bdb0(c);assert(culled==1&&lookup==1&&render==1&&c->esp==0x800c&&c->eip==0x6e518b);
CPU after_x360=*c;assert(mw_fe_shadows_hook(c,0x6e518b));
assert(lookup==1&&render==1&&!memcmp(c,&after_x360,sizeof *c));
unsigned opcodes[]={0xe8,0xe9,0xe8,0xe8};
unsigned targets[]={0x723fa0,0x0100bdb0,0x1000bdb0,0x0100bdb1};
for(unsigned i=0;i<4;i++){
 MR8(0x6e5186)=opcodes[i];MR32(0x6e5187)=targets[i]-0x6e518bu;
 lookup=render=0;*c=after_x360;assert(mw_fe_shadows_hook(c,0x6e518b));
 assert(lookup==1&&render==1&&c->esp==after_x360.esp);
}
''',fragments)

    def test_ground_sort_key_self_shadow_slot_and_transform(self):
        self.run_native(r'''
assert(mw_fe_shadows_init(1));MR32(0x925e90)=3;MR8(0x901830)=1;
MR32(0x982a20)=0x6000;MR32(0x6004)=2;MR32(0x9195e4+2*0x70)=4;
c->esi=0x3000;c->ebp=0x4000;c->edx=0xfffffffe;MR32(0x300c)=0x12345678;
MR32(0x4018)=0x7000;MR32(0x7000)=0x7100;MR8(0x7151)=0x52;
assert(mw_fe_shadows_branch(c,0x6e0b6e));assert(c->eax==0xfffffffe&&c->edx==0x6000&&c->ebx==0x52);
assert(MR32(0x3038)==((0xfffffffeu^0x12345678u)&0xffffffu|0x52000000u));
c->eax=0xabcdef;c->ecx=0x12345678;MR32(c->esp+0xd8)=0x55555555;
assert(mw_fe_shadows_branch(c,0x74e37f));assert(c->ecx==0x12345600&&MR32(c->esp+0xdc)==0xabcdef&&MR32(c->esp+0xd8)==0x55555555);
MR32(0x9195e4+2*0x70)=1;c->ecx=0x12345678;assert(mw_fe_shadows_branch(c,0x74e37f));assert(c->ecx==0x12345678);
MR32(0x982c80)=0x7200;MR8(0x7204)=4;mw_fe_shadows_hook(c,0x6c8323);assert(MR32(c->esp+0x54)==0xffc00000);
MR32(c->esp+0x54)=0;MR8(0x7204)=1;mw_fe_shadows_hook(c,0x6c8323);assert(!MR32(c->esp+0x54));
''')

    def test_bias_and_original_store_instructions(self):
        from tools.lift import Lifter
        image=Path('game/speed.exe')
        if not image.is_file():self.skipTest('requires canonical game image')
        lifter=Lifter(str(image),hooks=[0x6c8323],branch_hooks={0x74e37f:0x74e386})
        fragments=''
        for start,stop in ((0x6c8323,0x6c8329),(0x74e37f,0x74e386)):
            code,_=lifter.lift(start)
            fragments+='void sub_%08x(CPU*c){\n'%start+code[code.index(f'L_{start:08x}:'):code.index(f'    /* {stop:08x} ')]+ 'return;}\n'
        self.run_native(r'''
assert(mw_fe_shadows_init(1));MR32(0x925e90)=3;
unsigned resolutions[]={512,1024,2048,4096};float expected[]={2,2,2,4};
for(unsigned i=0;i<4;i++){MR32(0x93db3c)=resolutions[i];c->top=5;mw_fe_shadows_hook(c,0x6e551b);assert(MRF32(c->esp+8)==expected[i]&&c->top==5);}
MR32(0x925e90)=6;MRF32(c->esp+8)=.25f;mw_fe_shadows_hook(c,0x6e551b);assert(MRF32(c->esp+8)==.25f);
MR32(0x925e90)=3;MR8(0x901830)=1;MR32(0x982c80)=0x7000;MR8(0x7004)=4;c->eax=0x7100;MR32(0x7100)=0x1234;
sub_006c8323(c);assert(c->esi==c->esp+0x50&&c->edx==0x1234&&MR32(c->esp+0x54)==0xffc00000);
MR32(0x982a20)=0x6000;MR32(0x6004)=0;MR32(0x9195e4)=4;c->eax=123;c->ecx=255;MR32(c->esp+0xd8)=999;
sub_0074e37f(c);assert(c->ecx==0&&MR32(c->esp+0xdc)==123&&MR32(c->esp+0xd8)==999);
assert(mw_fe_shadows_init(0));c->eax=456;sub_0074e37f(c);assert(MR32(c->esp+0xd8)==456);
''',fragments=fragments)


if __name__=='__main__':unittest.main()
