from pathlib import Path
import subprocess
import tempfile
import unittest


HARNESS = r'''
#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
uint8_t *g_mem;
static const char *root;
static uint64_t now;
static unsigned clocks,sleeps,releases,acquires;
uint64_t host_qpc(void){clocks++;return now;}
void guest_wait_begin(void){releases++;}
void guest_wait_end(void){acquires++;}
int nanosleep(const struct timespec *time,struct timespec *remaining){
 assert(time->tv_sec==0&&time->tv_nsec==1000000);(void)remaining;sleeps++;return 0;
}
int fileio_resolve_game(const char *name,char *out,size_t size){
 int n=snprintf(out,size,"%s/%s",root,name);return n>0&&(size_t)n<size;
}
int mw_fixes_init(int);
int mw_fixes_hook(CPU*,uint32_t);
int mw_fixes_branch(CPU*,uint32_t);
'''


class MWFixesTests(unittest.TestCase):
    def run_native(self, body, mw=None, zpatch=None, fragments=''):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'scripts/MWFixes.ini').write_text(mw if mw is not None else
                '[Fixes]\nStabilityFixes=1\nPreventPurecall=1\nTimebugFix=0\nAddPurecallHandler=0\n')
            (root / 'scripts/ZPatchMW.ini').write_text(zpatch if zpatch is not None else
                '[Fixes]\nAICopCarCrashFix=1\nStutterFix=1\nBorderlessFixes=0\n')
            source = root / 'test.c'
            source.write_text(HARNESS + fragments + '\nint main(int argc,char **argv){\n'
                'assert(argc==2);root=argv[1];g_mem=calloc(1,0x1000000);assert(g_mem);\n'
                + body + '\nfree(g_mem);return 0;}\n')
            build = subprocess.run(['clang', '-O1', '-fno-strict-aliasing', '-Iruntime',
                str(source), 'runtime/mw_fixes.c', '-lm', '-o', str(root / 'test')],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(root / 'test'), str(root)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_disabled_hooks_preserve_all_cpu_state(self):
        self.run_native(r'''
CPU cpu={0},*c=&cpu;c->esp=0x1000;c->edi=0;c->edx=0x890970;c->eax=99;
CPU before=*c;assert(mw_fixes_init(0));
unsigned sites[]={0x43e005,0x57d105,0x4549bf,0x4f0e7a,0x642eaf};
for(unsigned i=0;i<5;i++){assert(!mw_fixes_branch(c,sites[i]));assert(!memcmp(c,&before,sizeof *c));}
unsigned hooks[]={0x464eea,0x464f4b,0x663dcd,0x663dd2};
for(unsigned i=0;i<4;i++){assert(mw_fixes_hook(c,hooks[i]));assert(!memcmp(c,&before,sizeof *c));}
assert(!clocks&&!sleeps);assert(!mw_fixes_hook(c,0x1234));assert(mw_fixes_branch(c,0x1234)==-1);
''')

    def test_specific_stability_conditions_and_exact_null_epilogue(self):
        self.run_native(r'''
assert(mw_fixes_init(1));CPU cpu={0},*c=&cpu;c->esp=0x2000;
c->edx=0x890970;c->eax=77;c->af=1;
assert(mw_fixes_branch(c,0x43e005));assert(c->eax==0&&c->zf&&c->pf&&!c->cf&&!c->of&&!c->sf&&!c->af);
c->edx=0x890974;c->eax=77;assert(!mw_fixes_branch(c,0x43e005));
assert(c->eax==77&&!c->zf&&!c->cf);
c->ecx=0;assert(mw_fixes_branch(c,0x57d105));assert(c->zf&&c->pf);
c->ecx=0x80000001;assert(!mw_fixes_branch(c,0x57d105));assert(c->sf&&!c->zf&&!c->cf&&!c->of);
c->edi=0;MR32(0x2000)=0xaabbccdd;MR32(0x2004)=0x11223344;MR32(0x2108)=0xabcdef;
uint8_t snapshot[0x110];memcpy(snapshot,g_mem+0x2000,sizeof snapshot);
assert(mw_fixes_branch(c,0x4549bf));
assert(c->esp==0x2108&&c->edi==0xaabbccdd&&c->esi==0x11223344&&c->eax==0);
assert(c->zf&&c->pf&&!c->af&&!c->cf&&!c->of&&!c->sf);
assert(!memcmp(snapshot,g_mem+0x2000,sizeof snapshot));
c->edi=0x3000;c->eax=77;assert(!mw_fixes_branch(c,0x4549bf));assert(c->eax==77&&c->esp==0x2108);
assert(mw_fixes_hook(c,0x464eea)&&c->eax==0);c->eax=77;
assert(mw_fixes_hook(c,0x464f4b)&&c->eax==0);
''')

    def test_ai_sentinel_and_float_difference_double_distance(self):
        self.run_native(r'''
assert(mw_fixes_init(1));CPU cpu={0},*c=&cpu;c->esp=0x1000;c->top=3;c->fcw=0x007f;
MR32(c->esp)=0xfffffff0;MR32(c->esp+4)=0x40;
assert(mw_fixes_branch(c,0x4f0e7a));assert(c->top==2&&c->st[2]==99999&&c->esp==0x1000);
MR32(c->esp)=0x2000;MR32(c->esp+4)=0x3000;
MRF32(0x2000)=3;MRF32(0x2004)=4;MRF32(0x2008)=12;
assert(mw_fixes_branch(c,0x4f0e7a));assert(c->top==1&&c->st[1]==13);
MRF32(0x2000)=.123456789f;MRF32(0x2004)=.987654321f;MRF32(0x2008)=.333333333f;
MRF32(0x3000)=.00001f;MRF32(0x3004)=.001f;MRF32(0x3008)=.01f;
double x=(float)(MRF32(0x2000)-MRF32(0x3000)),y=(float)(MRF32(0x2004)-MRF32(0x3004)),z=(float)(MRF32(0x2008)-MRF32(0x3008));
volatile double x2=x*x,y2=y*y,z2=z*z,sum=x2+y2;double expected=sqrt(sum+z2);
assert(mw_fixes_branch(c,0x4f0e7a));assert(c->st[c->top&7]==expected);
''')

    def test_stutter_exact_threshold_flow_and_call_pair(self):
        self.run_native(r'''
assert(mw_fixes_init(1));CPU cpu={0},*c=&cpu;c->esp=0x1000;c->top=2;c->st[2]=123;
assert(mw_fixes_branch(c,0x642eaf));
assert(mw_fixes_hook(c,0x663dcd));assert(sleeps==1&&!clocks&&releases==1&&acquires==1);
MR32(0x925e90)=3;MRF32(0x9259bc)=.02f;
c->esp+=4;c->top=1;mw_fixes_hook(c,0x663dd2);assert(c->st[1]==(double)(float)((double).02f*1.5));
now=10000;c->esp=0x1000;c->top=2;mw_fixes_hook(c,0x663dcd);assert(sleeps==1&&clocks==1);
MR32(0x925e90)=4;c->esp+=4;c->top=1;c->st[1]=456;mw_fixes_hook(c,0x663dd2);assert(c->st[1]==456);
now=10500;c->esp=0x1000;mw_fixes_hook(c,0x663dcd);assert(sleeps==2&&clocks==2);
now=11500;c->esp=0x1000;mw_fixes_hook(c,0x663dcd);assert(sleeps==2&&clocks==3);
MR32(0x925e90)=0;c->esp=0x1008;c->st[2]=456;mw_fixes_hook(c,0x663dd2);assert(c->st[2]==456);
assert(mw_fixes_init(0));assert(!mw_fixes_branch(c,0x642eaf));
''')

    def test_missing_ini_defaults_and_unsupported_or_malformed_options(self):
        self.run_native(r'''
assert(mw_fixes_init(1));CPU cpu={0},*c=&cpu;
assert(!mw_fixes_branch(c,0x642eaf));c->edx=0x890970;assert(!mw_fixes_branch(c,0x43e005));
''', mw='', zpatch='')
        for mw, zpatch in [('[Fixes]\nTimebugFix=1\n',''),
                           ('[Fixes]\nAddPurecallHandler=1\n',''),
                           ('','[Fixes]\nBorderlessFixes=1\n'),
                           ('[Fixes]\nStabilityFixes=\n',''),
                           ('','[Fixes]\nStutterFix=1junk\n')]:
            self.run_native('assert(!mw_fixes_init(1));', mw=mw, zpatch=zpatch)

    @unittest.skipUnless(Path('game/speed.exe').is_file(), 'requires canonical game image')
    def test_canonical_instructions_take_only_the_verified_static_branches(self):
        import hashlib
        from tools.lift import Lifter
        image = Path('game/speed.exe')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        branches = {0x43e005:0x43e20c,0x57d105:0x57d11f,0x4549bf:0x454a2a,
                    0x4f0e7a:0x4f0e7f,0x642eaf:0x642eda}
        lifter = Lifter(str(image), branch_hooks=branches, hooks=[0x663dcd,0x663dd2])
        code = r'''
static unsigned calls;
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
int guest_branch(CPU *c,uint32_t ip){int result=mw_fixes_branch(c,ip);assert(result>=0);return result;}
void guest_hook(CPU *c,uint32_t ip){assert(mw_fixes_hook(c,ip));}
static void finish(CPU *c,unsigned args){POP32(c->eip);c->esp+=args;}
void dispatch_indirect(CPU *c,uint32_t address){assert(address==0x1234);calls++;finish(c,0);}
void sub_007c5f80(CPU *c){c->eax=MR32(c->esp+4)+32;finish(c,0);}
void sub_004517c0(CPU *c){c->eax=0x55667788;finish(c,0);}
void sub_0045f340(CPU *c){calls++;FPUSH(12);finish(c,0);}
void sub_007c4b80(CPU *c){c->eax=1;FPOP();finish(c,0);}
void sub_0064cf00(CPU *c){calls++;finish(c,0);}
void sub_00642e60(CPU *c){calls++;FPUSH(123);finish(c,4);}
'''
        code += lifter.lift(0x4549b0)[0] + lifter.lift(0x57d0f0)[0]
        # Keep the actual call/branch and the original epilogue. The skipped
        # function body is unrelated to this specific bad-vtable guard.
        pure = lifter.lift(0x43e005)[0]
        prefix = 'void sub_0043e005(CPU *c){\n' + pure[pure.index('L_0043e005:'):pure.index('    /* 0043e00b ')]
        epilogue = pure[pure.index('L_0043e20c:'):]
        epilogue = epilogue[:epilogue.index('    POP32(c->eip); c->esp += 16u; return;')]
        code += prefix + '    return;\n' + epilogue + '    POP32(c->eip); c->esp += 16u; return;\n}\n'
        for start, stop in ((0x4f0e7a,0x4f0e7f),(0x642eaf,0x642eda)):
            fragment = lifter.lift(start)[0]
            code += fragment[:fragment.index(f'    /* {stop:08x} ')] + '    return;\n}\n'
        fragment = lifter.lift(0x663dcd)[0]
        code += 'void sub_00663dcd(CPU *c){\n' + fragment[fragment.index('L_00663dcd:'):fragment.index('    /* 00663dd6 ')] + '    return;\n}\n'
        self.run_native(r'''
assert(mw_fixes_init(1));CPU cpu={0},*c=&cpu;
c->esp=0x3000;MR32(c->esp)=0xabcdef;MR32(c->esp+4)=0;c->esi=111;c->edi=222;
sub_004549b0(c);assert(c->eax==0&&c->esp==0x3004&&c->eip==0xabcdef&&c->esi==111&&c->edi==222&&c->zf);
c->esp=0x3000;MR32(c->esp+4)=0x6000;MR8(0x6000)='A';MR8(0x6001)=0;
sub_004549b0(c);assert(c->eax==0x55667788&&c->esp==0x3004&&c->esi==111&&c->edi==222);
MR32(0x92fd94)=2;MR32(0x92fd8c)=0x6000;MR32(0x6000)=0;MR32(0x6004)=0x7000;
c->esp=0x3000;c->esi=999;calls=0;sub_0057d0f0(c);assert(calls==0&&c->esi==999&&c->esp==0x3004);
MR32(0x6000)=0x7000;MR32(0x7000)=0x7100;MR32(0x710c)=0x1234;
c->esp=0x3000;sub_0057d0f0(c);assert(calls==2&&c->esi==999&&c->esp==0x3004);
c->esp=0x3000;c->edx=0x890970;c->eax=77;c->fs_base=0x1000;
MR32(0x34b4)=0x12345678;MR32(0x3000)=11;MR32(0x3004)=22;MR32(0x3008)=33;MR32(0x300c)=44;MR32(0x34c0)=0xabcdef;
sub_0043e005(c);assert(c->eax==0&&c->edi==11&&c->esi==22&&c->ebp==33&&c->ebx==44&&c->esp==0x34d4&&c->eip==0xabcdef&&MR32(0x1000)==0x12345678);
c->esp=0x3000;c->top=3;MR32(c->esp)=0xfffffff0;MR32(c->esp+4)=0x40;calls=0;
sub_004f0e7a(c);assert(!calls&&c->st[c->top]==99999&&c->esp==0x3000);
c->zf=1;c->top=3;c->st[3]=42;sub_00642eaf(c);assert(!calls&&c->st[3]==42);
MR32(0x925e90)=3;MRF32(0x9259bc)=.02f;c->esp=0x4000;c->top=3;
sub_00663dcd(c);assert(calls==1&&c->esp==0x4004&&c->top==3&&MRF32(0x4008)==(float)((double).02f*1.5));
calls=0;
assert(mw_fixes_init(0));c->esp=0x3000;c->top=3;sub_004f0e7a(c);assert(calls==1&&c->st[c->top]==12&&c->esp==0x3000);
''', fragments=code)


if __name__ == '__main__':
    unittest.main()
