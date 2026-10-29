from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest


IMAGE = Path('out/installed/.nfsmw/runtime.exe')
SITES = [0x6dbd44, 0x6dbd4a, 0x6dbd54, 0x6dbd5a,
         0x6dbd64, 0x6dbd6a, 0x6dbd72, 0x6dbd78]
HARNESS = r'''
#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem;
static const char *configuration;
int fileio_resolve_game(const char *name,char *out,size_t n){
 assert(!strcmp(name,"scripts/NFSMWMotionBlurControllerSettings.ini"));
 return snprintf(out,n,"%s",configuration)>0;
}
int mw_motionblur_init(int);
int mw_motionblur_hook(CPU*,uint32_t);
void guest_hook(CPU *c,uint32_t ip){assert(mw_motionblur_hook(c,ip));}
'''


class MotionBlurTests(unittest.TestCase):
    def run_native(self, body, fragments=''):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'mod.ini'
            config.write_text('[Main]\nMotionBlurAmount = 0.85 // HQ amount\n'
                              'MotionBlurMinEffectiveSpeed = 20.0 ; HQ speed\n')
            source = root / 'test.c'
            source.write_text(HARNESS + fragments + '\nint main(int argc,char **argv){\n'
                              'configuration=argv[1];g_mem=calloc(1,0x1000000);assert(g_mem);\n'
                              'MRF32(0x8f9b10)=25;MRF32(0x8910c4)=1.1f;\n'
                              + body + '\nfree(g_mem);return 0;}\n')
            binary = root / 'test'
            build = subprocess.run(['clang', '-O1', '-Iruntime', str(source),
                                    'runtime/mw_motionblur.c', '-lm', '-o', str(binary)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), str(config)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_hq_settings_and_cpu_context_preserve_standard_behavior(self):
        self.run_native(r'''
CPU cpu={0},other={0},*c=&cpu;c->esp=0x1000;c->fcw=0x027f;c->st[0]=0.75;
CPU before=*c;assert(mw_motionblur_init(0));
assert(MRF32(0x8f9b10)==25);
unsigned starts[]={0x6dbd44,0x6dbd54,0x6dbd64,0x6dbd72};
for(unsigned i=0;i<4;i++){
 assert(mw_motionblur_hook(c,starts[i]));assert(!memcmp(c,&before,sizeof *c));
 assert(mw_motionblur_hook(c,starts[i]+6));assert(!memcmp(c,&before,sizeof *c));
}
assert(mw_motionblur_init(1)&&MRF32(0x8f9b10)==20);
for(unsigned i=0;i<4;i++){
 *c=before;assert(mw_motionblur_hook(c,starts[i]));assert(!memcmp(c,&before,sizeof *c));
 c->st[0]=9;assert(mw_motionblur_hook(c,starts[i]+6));
 assert(c->st[0]==X87R2(.75,(double).85f,.75*(double).85f));
 c->st[0]=before.st[0];assert(!memcmp(c,&before,sizeof *c));
}
assert(MRF32(0x8910c4)==1.1f);
*c=before;mw_motionblur_hook(c,starts[0]);other=*c;other.st[0]=9;
mw_motionblur_hook(&other,starts[0]+6);assert(other.st[0]==9);
c->st[0]=9;c->esp+=4;mw_motionblur_hook(c,starts[0]+6);assert(c->st[0]==9);
assert(mw_motionblur_init(0)&&MRF32(0x8f9b10)==25);
assert(!mw_motionblur_hook(c,0x1234));
''')

    @unittest.skipUnless(IMAGE.is_file(), 'requires verified supported executable')
    def test_actual_four_game_multiplications_match_the_pinned_mod(self):
        from tools.lift import Lifter
        self.assertEqual(hashlib.sha256(IMAGE.read_bytes()).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        lifter = Lifter(str(IMAGE), hooks=SITES)
        fragments = ''
        for start, stop in [(0x6dbd44, 0x6dbd4e), (0x6dbd54, 0x6dbd5e),
                            (0x6dbd64, 0x6dbd6e), (0x6dbd72, 0x6dbd7c)]:
            code, _ = lifter.lift(start)
            fragments += code[:code.index(f'    /* {stop:08x} ')] + '}\n'
        self.run_native(r'''
CPU cpu={0},*c=&cpu;
void (*functions[])(CPU*)={sub_006dbd44,sub_006dbd54,sub_006dbd64,sub_006dbd72};
unsigned offsets[]={0x28,0x2c,0x30,0x34};
for(unsigned enabled=0;enabled<2;enabled++){
 assert(mw_motionblur_init(enabled));
 for(unsigned i=0;i<4;i++)for(unsigned pc=0;pc<2;pc++){
  memset(c,0,sizeof *c);c->esp=0x1000;c->fcw=pc?0x027f:0x007f;
  c->top=3;c->st[3]=.123456789;c->cf=c->zf=c->sf=c->of=1;
  double factor=enabled?(double).85f:(double)1.1f;
  float expected=(float)X87R2(c->st[3],factor,c->st[3]*factor);
  functions[i](c);assert(MRF32(0x1000+offsets[i])==expected);
  assert(c->top==4&&c->cf&&c->zf&&c->sf&&c->of&&c->esp==0x1000);
 }
}
''', fragments)

    def test_missing_ini_uses_pinned_defaults_and_invalid_values_do_not_activate(self):
        self.run_native(r'''
assert(!remove(configuration));
assert(mw_motionblur_init(1)&&MRF32(0x8f9b10)==1);
assert(mw_motionblur_init(0)&&MRF32(0x8f9b10)==25);
char longvalue[160];memset(longvalue,' ',sizeof longvalue);memcpy(longvalue,"0.85",4);
memcpy(longvalue+150,"junk",5);
const char *values[]={"nan","0.5junk","   ","1e1000","",longvalue};
for(unsigned i=0;i<6;i++){
 FILE *file=fopen(configuration,"w");assert(file);
 fprintf(file,"[Main]\nMotionBlurAmount = %s\nMotionBlurMinEffectiveSpeed = 20\n",values[i]);
 assert(!fclose(file));assert(!mw_motionblur_init(1));assert(MRF32(0x8f9b10)==25);
}
''')


if __name__ == '__main__':
    unittest.main()
