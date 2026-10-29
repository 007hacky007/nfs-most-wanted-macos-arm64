from pathlib import Path
import subprocess
import tempfile
import unittest


class AutomationTests(unittest.TestCase):
    def test_script_drives_guest_keys_in_frame_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            script=root/'input.txt';script.write_text('10 RETURN down\n12 RETURN up\n20 A down\n22 A up\n')
            bad=root/'bad.txt';bad.write_text('20 RETURN down\n10 RETURN up\n')
            commands=root/'commands.txt';commands.write_text('RIGHT press\nDUMP\nCLICK 0.5 0.65\nBLUR 100\nQUIT\n')
            harness=root/'test.c'
            harness.write_text('''#include <assert.h>
#include <stdint.h>
int automation_load(const char *),automation_open_commands(const char *);void automation_frame(uint64_t);
static int keys,messages,dumps,clicks,quits,blurs;
void lifecycle_request_quit(const char *reason){(void)reason;quits++;}
void lifecycle_simulate_blur(long ms){assert(ms==100);blurs++;}
void metal_request_frame_dump(void){dumps++;}
void metal_request_click(double x,double y){assert(x==.5&&y==.65);clicks++;}
void kbd_set_key(int source,unsigned key,int down){assert(source==1);assert(key==0x1c||key==0x1e||key==0xcd);keys+=down?1:10;}
void kbd_post(uint32_t message,uint32_t w,uint32_t l){(void)w;(void)l;assert(message==0x100||message==0x101||message==0x102);messages++;}
int main(int argc,char **argv){(void)argc;assert(automation_load(argv[1]));automation_frame(9);assert(!keys);
automation_frame(10);assert(keys==1);automation_frame(12);assert(keys==11);
automation_frame(22);assert(keys==22&&messages==6);assert(!automation_load(argv[2]));
assert(automation_open_commands(argv[3]));automation_frame(24);assert(keys==23&&dumps==1&&clicks==1&&quits==1&&blurs==1);
automation_frame(28);assert(keys==33&&messages==8);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(harness),'runtime/automation.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test'),str(script),str(bad),str(commands)],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
