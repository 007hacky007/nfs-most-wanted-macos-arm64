from pathlib import Path
import subprocess
import tempfile
import unittest


class AutomationDigitTests(unittest.TestCase):
    def test_digit_commands_reach_directinput_and_release_after_four_frames(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);commands=root/'commands';commands.write_text('1 press\n0 press\n9 press\n')
            source=root/'digits.c'
            source.write_text('''#include "kbd.h"
#include <assert.h>
#include <stdint.h>
int automation_open_commands(const char*);void automation_frame(uint64_t);
uint32_t host_ms(void){static uint32_t now;return ++now;}
void metal_request_frame_dump(void){}void lifecycle_request_quit(const char*s){(void)s;}
void lifecycle_simulate_blur(long x){(void)x;}void metal_request_click(double x,double y){(void)x;(void)y;}
int main(int argc,char**argv){assert(argc==2&&automation_open_commands(argv[1]));automation_frame(0);
assert(kbd_key_down(0x02)&&kbd_key_down(0x0b)&&kbd_key_down(0x0a));
automation_frame(3);assert(kbd_key_down(0x02));automation_frame(4);
assert(!kbd_key_down(0x02)&&!kbd_key_down(0x0b)&&!kbd_key_down(0x0a));assert(kbd_key_presses(0x02)==1);return 0;}
''')
            binary=root/'digits'
            result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-Iruntime',str(source),
                'runtime/automation.c','runtime/keyboard.c','-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(binary),str(commands)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
