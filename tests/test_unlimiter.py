from pathlib import Path
import subprocess
import tempfile
import unittest


class UnlimiterTests(unittest.TestCase):
    def test_native_added_car_and_traffic_bounds_preserve_registers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'test.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;
void mw_unlimiter_init(int);
int mw_unlimiter_hook(CPU *,uint32_t);
int main(void){
 g_mem=calloc(1,0xA00000);CPU cpu={0},*c=&cpu;
 mw_unlimiter_init(0);c->eax=98;c->sf=0;c->of=0;
 assert(mw_unlimiter_hook(c,0x6690BE)&&!c->sf);
 assert(!mw_unlimiter_hook(c,0x1234));
 mw_unlimiter_init(1);c->esi=0x10000;MR32(c->esi-12)=99*208+8;
 assert(mw_unlimiter_hook(c,0x756AAD));
 MR32(c->esi-12)=8;assert(mw_unlimiter_hook(c,0x756AAD));
 uint32_t addresses[]={0x6690BE,0x7398A9,0x73995E,0x7515FE,0x759916,0x75E6F7,0x75E7B7};
 for(unsigned i=0;i<sizeof(addresses)/sizeof(addresses[0]);i++){
  c->eax=c->ecx=c->esi=98;
  assert(mw_unlimiter_hook(c,addresses[i]));assert(c->sf!=c->of&&!c->zf);
  assert(c->eax==98&&c->ecx==98&&c->esi==98);
  c->eax=c->ecx=c->esi=99;
  assert(mw_unlimiter_hook(c,addresses[i]));assert(c->zf&&c->sf==c->of);
 }
 c->esi=98*208;assert(mw_unlimiter_hook(c,0x739904)&&c->sf!=c->of);
 c->esi=99*208;assert(mw_unlimiter_hook(c,0x739904)&&c->zf);
 c->ebp=98*208;assert(mw_unlimiter_hook(c,0x7B3881)&&c->sf!=c->of);
 c->eax=84;assert(mw_unlimiter_hook(c,0x73990D)&&c->eax==1);
 c->eax=0;c->ebx=0x5000;c->zf=1;
 assert(mw_unlimiter_hook(c,0x75C710)&&!c->zf&&MR32(c->ebx)==1&&c->edx==1);
 uint32_t traffic[]={0x439B7A,0x410963,0x4265C3};
 for(unsigned i=0;i<3;i++){
  c->esi=c->edi=19;assert(mw_unlimiter_hook(c,traffic[i])&&c->cf);
  c->esi=c->edi=20;assert(mw_unlimiter_hook(c,traffic[i])&&c->zf&&!c->cf);
 }
 c->eax=25;c->ecx=10;assert(mw_unlimiter_hook(c,0x42625A)&&c->ecx==20&&!c->cf&&!c->zf);
 c->esp=0x1000;c->zf=1;MR8(c->esp+23)=0;
 assert(mw_unlimiter_hook(c,0x74251E)&&MR8(c->esp+23)==1);
 c->zf=0;MR8(c->esp+23)=0;assert(mw_unlimiter_hook(c,0x74251E)&&!MR8(c->esp+23));
 assert(!mw_unlimiter_hook(c,0x1234));
 free(g_mem);
}
''')
            subprocess.run(['clang', '-O1', '-Iruntime', str(source),
                            'runtime/mw_unlimiter.c', '-o', str(root / 'test')],
                           check=True, capture_output=True)
            subprocess.run([str(root / 'test')], check=True, capture_output=True)


    @unittest.skipUnless(Path('game/speed.exe').is_file(), 'requires local supported executable')
    def test_lifted_hash_lookup_finds_a_car_beyond_original_table(self):
        from tools.lift import Lifter
        code, _ = Lifter('game/speed.exe', hooks=[0x73995E]).lift(0x739940)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'test.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;
void mw_unlimiter_init(int);
int mw_unlimiter_hook(CPU *,uint32_t);
void guest_hook(CPU *c,uint32_t ip){assert(mw_unlimiter_hook(c,ip));}
''' + code + '''
int main(void){
 g_mem=calloc(1,0xA00000);CPU cpu={0},*c=&cpu;
 mw_unlimiter_init(1);c->esi=0x10000;MR32(c->esi-12)=99*208+8;
 assert(mw_unlimiter_hook(c,0x756AAD));
 MR32(0x9B09D8)=0x10000;MR32(0x10000+98*208+0x50)=0x12345678;
 c->esp=0x1000;MR32(c->esp)=0xABCDEF;MR32(c->esp+4)=0x12345678;
 sub_00739940(c);
 assert(c->eax==0x10000+98*208&&c->eip==0xABCDEF&&c->esp==0x1004);
 free(g_mem);
}
''')
            subprocess.run(['clang', '-O1', '-Iruntime', str(source),
                            'runtime/mw_unlimiter.c', '-o', str(root / 'test')],
                           check=True, capture_output=True)
            subprocess.run([str(root / 'test')], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
