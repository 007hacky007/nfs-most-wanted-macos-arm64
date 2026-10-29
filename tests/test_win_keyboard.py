from pathlib import Path
import subprocess
import tempfile
import unittest


class WinKeyboardTests(unittest.TestCase):
    def test_layout_mapping_unicode_and_pressed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;int win_keyboard_call(CPU *,const char *,uint32_t *);
void mem_commit(uint32_t a,uint32_t n){assert(a+n<65536);}
int kbd_key_down(unsigned scan){return scan==0x1e||scan==0x36||scan==0x9d||scan==0xb8;}
int main(void){g_mem=calloc(1,65536);CPU cpu={0},*c=&cpu;c->esp=0x1000;uint32_t r;
assert(win_keyboard_call(c,"GetKeyboardLayout",&r)&&r==0x04090409);
MR32(c->esp)=13;MR32(c->esp+4)=0;assert(win_keyboard_call(c,"MapVirtualKeyExA",&r)&&r==0x1c);
MR32(c->esp)=0x1e;MR32(c->esp+4)=1;assert(win_keyboard_call(c,"MapVirtualKeyA",&r)&&r=='A');
MR32(c->esp)='A';MR32(c->esp+4)=0x1e;MR32(c->esp+8)=0x2000;MR32(c->esp+12)=0x3000;MR32(c->esp+16)=8;
assert(win_keyboard_call(c,"ToUnicode",&r)&&r==1&&MR16(0x3000)=='a');
MR8(0x2010)=0x80;assert(win_keyboard_call(c,"ToUnicode",&r)&&r==1&&MR16(0x3000)=='A');
MR32(c->esp)='A';assert(win_keyboard_call(c,"GetKeyState",&r)&&r==0x8000);
MR32(c->esp)=0x4000;assert(win_keyboard_call(c,"GetKeyboardState",&r)&&r==1&&MR8(0x4041)==0x80);
assert(MR8(0x4010)==0x80&&MR8(0x4011)==0x80&&MR8(0x4012)==0x80);
MR32(c->esp)=16;assert(win_keyboard_call(c,"GetKeyState",&r)&&r==0x8000);
free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/win_keyboard.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
