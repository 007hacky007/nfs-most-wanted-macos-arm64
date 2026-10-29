from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

class CaptureTests(unittest.TestCase):
    def test_failure_capture_is_isolated_and_preserves_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "cpu.h"
#include "hq_capture.h"
#include <assert.h>
#include <stdlib.h>
#include <signal.h>
#include <unistd.h>
#include <sys/wait.h>
static CPU *fault_cpu;
static void capture_signal(int sig){(void)sig;hq_capture_fault(fault_cpu,0x60a11037,0x4c40c0,"sub_004c40c0_full5");_exit(3);}
uint8_t *g_mem,g_cbits[1u<<15];
int main(int argc,char**argv){assert(argc==2);g_mem=calloc(1,0x2600000);memset(g_cbits,255,sizeof g_cbits);
setenv("NFSMW_HQ_CAPTURE_DIR",argv[1],1);CPU c={0};c.eax=0x123;c.esp=0x100;MR32(c.esp)=0xabcdef;
CPU before=c;MR8(MW_BASE+17)=0x5a;MR8(0x1000021)=0x6b;MR8(0x1400022)=0x7c;MR8(0x1800023)=0x8d;MR8(0x1c00024)=0x9e;MR8(0x2400025)=0xaf;MR32(0x9b09d8)=0x9000;MR32(0x1847814)=2;MR8(0x9000)=0xab;hq_capture(&c,"cartypes",0x401234);
hq_capture_prepare();fault_cpu=&c;pid_t child=fork();assert(child>=0);
if(!child){signal(SIGUSR1,capture_signal);raise(SIGUSR1);_exit(9);}
int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==3);
assert(!memcmp(&c,&before,sizeof c));assert(strstr(hq_capture_path("missing-code.bin"),"missing-code.bin"));free(g_mem);}
''')
            subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/hq_capture.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test'),str(root)],check=True,capture_output=True)
            manifest=json.loads((root/'0001-cartypes.json').read_text())
            fault=json.loads((root/'fault.json').read_text())
            self.assertEqual(fault['fault_address'],0x60a11037)
            self.assertEqual(fault['native_body'],'sub_004c40c0_full5')
            self.assertEqual((root/'fault.game.bin').stat().st_size,manifest['game_size'])
            self.assertEqual(manifest['address'],0x401234)
            self.assertEqual(manifest['return_address'],0xabcdef)
            self.assertEqual((root/'0001-cartypes.game.bin').stat().st_size,manifest['game_size'])
            self.assertEqual((root/'0001-cartypes.game.bin').read_bytes()[17],0x5a)
            self.assertEqual((root/'0001-cartypes.asi.bin').read_bytes()[0x21],0x6b)
            self.assertEqual((root/'0001-cartypes.cpu.bin').stat().st_size,manifest['cpu_size'])
            self.assertEqual((root/'0001-cartypes.rain.bin').read_bytes()[0x22],0x7c)
            self.assertEqual((root/'0001-cartypes.unlimiter.bin').read_bytes()[0x23],0x8d)
            self.assertEqual((root/'0001-cartypes.car-types.bin').stat().st_size,416)
            self.assertEqual((root/'0001-cartypes.car-types.bin').read_bytes()[0],0xab)
            self.assertEqual(manifest['car_type_count'],2)
            self.assertEqual((root/'0001-cartypes.extraoptions.bin').read_bytes()[0x24],0x9e)
            self.assertEqual((root/'0001-cartypes.xenon.bin').read_bytes()[0x25],0xaf)
            self.assertEqual((root/'fault.rain.bin').read_bytes()[0x22],0x7c)
            self.assertEqual((root/'fault.unlimiter.bin').read_bytes()[0x23],0x8d)
            self.assertEqual((root/'fault.extraoptions.bin').read_bytes()[0x24],0x9e)
            self.assertEqual((root/'fault.xenon.bin').read_bytes()[0x25],0xaf)

    @unittest.skipUnless(sys.platform=='darwin','requires the native macOS memory handler')
    def test_memory_handler_captures_the_faulting_guest_address_and_native_body(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'handler.c'
            source.write_text('''#include "cpu.h"
#include "hq_capture.h"
#include <assert.h>
#include <stdlib.h>
void mem_init(void),mem_commit(uint32_t,uint32_t),mem_fault_handler_install(void);
extern CPU *g_cur_cpu;
uint32_t guest_fn_from_host(const void*pc){(void)pc;return 0x401234;}
const char*guest_fn_name_from_host(const void*pc){(void)pc;return "sub_00401234_full1";}
int main(int argc,char**argv){assert(argc==2);setenv("NFSMW_HQ_CAPTURE_DIR",argv[1],1);
mem_init();mem_commit(0x10000,0x1000);mem_fault_handler_install();hq_capture_prepare();
CPU c={0};c.esp=0x10000;c.eax=0xabc;c.fcw=0x27f;MR32(c.esp)=0xdeadbeef;g_cur_cpu=&c;
return *(volatile uint32_t*)(g_mem+0x600000);}
''')
            result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-DNFS_HQ_MODULES=1','-Iruntime',str(source),'runtime/mem.c','runtime/hq_capture.c','-o',str(root/'handler')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'handler'),str(root)],capture_output=True,text=True)
            self.assertEqual(result.returncode,3,result.stderr)
            record=json.loads((root/'fault.json').read_text())
            self.assertEqual(record['fault_address'],0x600000)
            self.assertEqual(record['native_body'],'sub_00401234_full1')
            self.assertEqual(record['guest_function'],0x401234)
            self.assertTrue(record['complete'])
            self.assertEqual((root/'fault.cpu.bin').stat().st_size,record['cpu_size'])

if __name__=='__main__':unittest.main()
