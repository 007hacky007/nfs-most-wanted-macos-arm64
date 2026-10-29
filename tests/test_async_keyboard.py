from pathlib import Path
import subprocess,tempfile,unittest

class AsyncKeyboardTests(unittest.TestCase):
    def test_press_latch_tracks_merged_sources_and_short_taps_without_consuming_held_state(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'async.c'
            source.write_text('''#include "cpu.h"
#include "kbd.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;int win_keyboard_call(CPU*,const char*,uint32_t*);
uint32_t host_ms(void){static uint32_t now;return ++now;}
void mem_commit(uint32_t a,uint32_t n){assert(a+n<0x10000);}
static CPU c;static uint32_t query(const char*name,unsigned vk){MR32(c.esp)=vk;CPU before=c;uint32_t out=99;
assert(win_keyboard_call(&c,name,&out)&&!memcmp(&before,&c,sizeof c));return out;}
int main(void){g_mem=calloc(1,0x10000);c.esp=0x100;c.eax=123;c.st[2]=1.25;
assert(!query("GetAsyncKeyState",118));kbd_set_key(KSRC_SCRIPT,0x41,1);
assert(query("GetKeyState",118)==0x8000&&query("GetAsyncKeyState",118)==0x8001&&query("GetAsyncKeyState",118)==0x8000);
kbd_set_key(KSRC_HOST,0x41,1);kbd_set_key(KSRC_SCRIPT,0x41,0);assert(query("GetAsyncKeyState",118)==0x8000);
kbd_set_key(KSRC_HOST,0x41,0);assert(!query("GetAsyncKeyState",118));
kbd_set_key(KSRC_SCRIPT,0x41,1);kbd_set_key(KSRC_SCRIPT,0x41,0);
for(unsigned i=0;i<3000;i++){kbd_set_key(KSRC_HOST,0x23,1);kbd_set_key(KSRC_HOST,0x23,0);}
assert(query("GetAsyncKeyState",118)==1&&!query("GetAsyncKeyState",118));assert(query("GetAsyncKeyState",72)==1&&!query("GetAsyncKeyState",72));
kbd_set_key(KSRC_SCRIPT,0x36,1);assert(query("GetAsyncKeyState",16)==0x8001&&query("GetAsyncKeyState",0xa1)==0x8001);
assert(query("GetAsyncKeyState",16)==0x8000);kbd_release_source(KSRC_SCRIPT);
kbd_set_key(KSRC_HOST,0xc5,1);assert(query("GetAsyncKeyState",19)==0x8001);kbd_set_key(KSRC_HOST,0xc5,0);
kbd_set_key(KSRC_HOST,0x46,1);assert(query("GetAsyncKeyState",145)==0x8001);kbd_set_key(KSRC_HOST,0x46,0);
assert(!query("GetAsyncKeyState",256)&&!query("GetAsyncKeyState",0xffffffffu));free(g_mem);}
''')
            result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-Iruntime',str(source),'runtime/keyboard.c','runtime/win_keyboard.c','-o',str(root/'async')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'async')],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
