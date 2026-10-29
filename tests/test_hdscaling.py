from pathlib import Path
import hashlib
import re
import subprocess
import tempfile
import unittest


IMAGE = Path('out/installed/.nfsmw/runtime.exe')
SITES = [0x585d7f, 0x6d1502, 0x570460, 0x570485, 0x57049a, 0x5704c3, 0x599f16]
HARNESS = r'''
#include "cpu.h"
#include "widescreen.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;
static unsigned clears;
int metal_display_hz(void){return 120;}
void com_widescreen_postfx(unsigned gamma,unsigned border){(void)gamma;(void)border;}
void com_clear_movie_borders(void){clears++;}
void dispatch_patch(uint32_t address,guest_fn_t function){(void)address;(void)function;assert(0);}
uint32_t gheap_alloc(int heap,uint32_t size,int zero){(void)heap;(void)size;(void)zero;assert(0);return 0;}
uint32_t call_guest(CPU*c,uint32_t function,int count,const uint32_t*args){(void)c;(void)function;(void)count;(void)args;assert(0);return 0;}
void gamepad_set_stick_deadzones(float left,float right){(void)left;(void)right;assert(0);}
void kbd_set_key(int source,unsigned key,int down){(void)source;(void)key;(void)down;assert(0);}
void kbd_post(uint32_t message,uint32_t wp,uint32_t lp){(void)message;(void)wp;(void)lp;assert(0);}

void mw_hdscaling_init(int enabled);
int mw_hdscaling_hook(CPU *c,uint32_t ip);
void guest_hook(CPU *c,uint32_t ip){assert(mw_hdscaling_hook(c,ip));}
'''


class HDScalingTests(unittest.TestCase):
    def run_native(self, body, fragments=''):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.c'
            source.write_text(HARNESS + fragments + '\nint main(void){\n'
                              'g_mem=calloc(1,0x10000);assert(g_mem);\n'
                              + body + '\nfree(g_mem);return 0;}\n')
            command = ['clang', '-O1', '-Iruntime', str(source),
                       'runtime/mw_widescreen.c', 'runtime/mw_hdscaling.c']
            binary = Path(tmp) / 'test'
            build = subprocess.run(command + ['-lm', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_known_fonts_use_original_logical_sizes_without_changing_textures(self):
        self.run_native(r'''
CPU cpu={0},*c=&cpu;mw_hdscaling_init(1);
const unsigned hashes[]={0xa87927be,0xab6215c1,0x545570c6,0xe0463afa,0xc7bd87ce,0x01424892};
const unsigned widths[]={256,256,256,512,128,128},heights[]={256,256,256,512,64,64};
for(unsigned i=0;i<6;i++){
 c->esp=0x1000;c->ecx=0x2000;MR32(0x2008)=0x3000;MR32(0x3024)=hashes[i];
 MR16(0x3044)=2048;MR16(0x3046)=1024;c->edi=73;c->esi=1024;c->eax=74;
 c->cf=c->zf=c->sf=c->of=1;
 assert(mw_hdscaling_hook(c,0x585d7f));
 assert(MR32(0x1024)==widths[i]&&c->esi==heights[i]&&c->edi==73&&c->eax==74);
 c->ecx=0x3000;c->eax=1024;c->edx=2048;
 assert(mw_hdscaling_hook(c,0x6d1502));
 assert(c->eax==heights[i]&&c->edx==widths[i]&&MR32(0x1018)==widths[i]);
 assert(MR16(0x3044)==2048&&MR16(0x3046)==1024&&c->cf&&c->zf&&c->sf&&c->of);
}
MR32(0x3024)=0xdeadbeef;c->ecx=0x3000;CPU before=*c;
assert(mw_hdscaling_hook(c,0x6d1502)&&!memcmp(c,&before,sizeof *c));
c->ecx=0x2000;before=*c;assert(mw_hdscaling_hook(c,0x585d7f)&&!memcmp(c,&before,sizeof *c));
mw_hdscaling_init(0);
for(unsigned i=0;i<7;i++){before=*c;unsigned sites[]={0x585d7f,0x6d1502,0x570460,0x570485,0x57049a,0x5704c3,0x599f16};
 assert(mw_hdscaling_hook(c,sites[i])&&!memcmp(c,&before,sizeof *c));}
assert(!mw_hdscaling_hook(c,0x1234));
''')

    @unittest.skipUnless(IMAGE.is_file(), 'requires verified supported executable')
    def test_real_game_instructions_use_logical_dimensions_and_fit_movie_once(self):
        from tools.lift import Lifter
        self.assertEqual(hashlib.sha256(IMAGE.read_bytes()).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        lifter = Lifter(str(IMAGE), hooks=SITES)
        fragments = ''
        for start, stop in [(0x585d60,0x585d83),(0x6d14f6,0x6d1506),
                            (0x57045c,0x570466),(0x570481,0x57048b),
                            (0x570496,0x5704a0),(0x5704bf,0x5704c5),
                            (0x599f05,0x599f22)]:
            code, _ = lifter.lift(start)
            fragments += code[:code.index(f'    /* {stop:08x} ')] + '}\n'
        self.run_native(r'''
CPU cpu={0},*c=&cpu;
for(unsigned enabled=0;enabled<2;enabled++){
 mw_hdscaling_init(enabled);memset(c,0,sizeof *c);
 c->esp=0x1000;c->ecx=0x2000;MR32(0x2008)=0x3000;MR32(0x3024)=0xc7bd87ce;
 MR16(0x3044)=1024;MR16(0x3046)=512;MR32(0x1004)=0x4000;MR16(0x4004)=5;
 sub_00585d60(c);assert(c->st[c->top&7]==(enabled?128:1024));
 assert(c->esi==(enabled?64:512)&&c->edi==4);
 memset(c,0,sizeof *c);c->esp=0x1000;c->ecx=0x3000;
 sub_006d14f6(c);assert(c->st[c->top&7]==(enabled?128:1024));
 assert(c->eax==(enabled?64:512)&&c->edx==(enabled?128:1024));
 c->esi=0x3000;c->edi=100;c->ebx=200;c->esp=0x1000;
 sub_0057045c(c);assert(MR32(0x1014)==100+(enabled?16:1024));
 sub_00570481(c);assert(MR32(0x101c)==100+(enabled?16:1024));
 sub_00570496(c);assert(MR32(0x101c)==200+(enabled?16:512));
 sub_005704bf(c);assert(c->eax==200+(enabled?16:512));
 c->edi=0x3000;c->ecx=0x123456;c->esp=0x1000;
 MR16(0x3044)=1920;MR16(0x3046)=1080;MR32(0x1038)=640;
 sub_00599f05(c);assert(c->eax==(enabled?1024:1920)&&c->edx==(enabled?512:1080));
 assert(MR32(0x100c)==c->eax&&MR32(0x1020)==c->ecx);
}
ws_set_resolution(1920,1080);mw_hdscaling_init(1);memset(c,0,sizeof *c);
c->esp=0x1000;c->ebx=0x2000;MRF32(0x2030)=640;MRF32(0x2044)=480;
MR32(0x1048)=0x3000;MRF32(0x1014)=0;MRF32(0x1018)=0;MRF32(0x101c)=1;MRF32(0x1020)=1;
assert(ws_hook(c,0x59a03f));assert(clears==1);
assert(fabsf(MRF32(0x1000)+2.f/3.f)<.00001&&MRF32(0x1004)==-.5f);
assert(MRF32(0x1018)==0&&MRF32(0x1020)==1);
assert(MR16(0x3044)==1920&&MR16(0x3046)==1080);
''', fragments)

    def test_hook_markers_match_the_seven_instruction_boundaries(self):
        source = Path('runtime/mw_hdscaling.c').read_text()
        self.assertEqual({int(a,16) for a in re.findall(r'HOOK_SITE\((0x[0-9a-fA-F]+)\)', source)}, set(SITES))


if __name__ == '__main__':
    unittest.main()
