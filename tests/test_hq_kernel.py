from pathlib import Path
import subprocess
import tempfile
import unittest

class KernelModuleTests(unittest.TestCase):
    def test_wide_module_apis_and_address_queries_preserve_guest_cpu(self):
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);source=root/'kernel.c'
            source.write_text('''#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
uint8_t *g_mem,g_cbits[1u<<15];static uint32_t error;
int hq_kernel_call(CPU*,const char*,uint32_t*);
int hq_kernel_export_allowed(const char*);
uint32_t win32_module_name_handle(const char*n){return !n?0x400000:!strcmp(n,"kernel32.dll")?0x400000:!strcmp(n,"nfsmwunlimiter.asi")?0x1800000:0;}
uint32_t module_from_address(uint32_t a){return a>=0x1800000&&a<0x184d000?0x1800000:0;}
int module_file_name(uint32_t h,char*out,int n){if(h!=0x1800000)return 0;snprintf(out,n,"C:\\\\NFSU2\\\\scripts\\\\nfsmwunlimiter.asi");return 1;}
uint32_t win32_command_line(void){return 0x600;}
uint32_t gheap_alloc(int h,uint32_t n,int z){assert(h==1&&n<100&&z==0);return 0x800;}
int win32_ext_call(CPU*c,const char*n,uint32_t*r){if(!strcmp(n,"CreateEventA")){assert(!MR32(c->esp+12));*r=0x70001000;return 1;}assert(!strcmp(n,"InitializeCriticalSectionAndSpinCount")&&MR32(c->esp)==0x700&&MR32(c->esp+4)==4000);*r=1;return 1;}
void gheap_free(int h,uint32_t p){assert(h==1&&p==0x800);}
int fileio_call(CPU*c,const char*n,uint32_t*r){assert(!strcmp(n,"CreateFileA")&&!strcmp((char*)g_mem+MR32(c->esp),"\\xc3\\xa9.ini"));*r=0x12340000;return 1;}
void win32_set_last_error(CPU*c,uint32_t e){(void)c;error=e;}
static void wide(uint32_t p,const char*s){for(unsigned i=0;;i++){MR16(p+2*i)=(unsigned char)s[i];if(!s[i])break;}}
int main(void){g_mem=calloc(1,0x2000000);memset(g_cbits,255,sizeof g_cbits);CPU c={0};c.esp=0x1000;c.eax=77;c.st[2]=1.25;CPU before=c;uint32_t result=99;
assert(!hq_kernel_export_allowed("LCMapStringEx")&&hq_kernel_export_allowed("LCMapStringW")&&hq_kernel_export_allowed("InitializeCriticalSectionEx"));
wide(0x200,"nfsmwunlimiter.asi");MR32(c.esp)=0x200;assert(hq_kernel_call(&c,"GetModuleHandleW",&result)&&result==0x1800000);
wide(0x200,"api-ms-win-core-test.dll");MR32(c.esp)=0x200;MR32(c.esp+4)=0;MR32(c.esp+8)=0x800;
assert(hq_kernel_call(&c,"LoadLibraryExW",&result)&&!result&&error==126);
wide(0x200,"kernel32.dll");assert(hq_kernel_call(&c,"LoadLibraryExW",&result)&&result==0x400000);
MR32(c.esp)=6;MR32(c.esp+4)=0x1801234;MR32(c.esp+8)=0x400;
assert(hq_kernel_call(&c,"GetModuleHandleExA",&result)&&result==1&&MR32(0x400)==0x1800000);
MR32(c.esp+4)=0x401000;assert(hq_kernel_call(&c,"GetModuleHandleExW",&result)&&result==1&&MR32(0x400)==0x400000);
MR32(c.esp+4)=0x70000000;assert(hq_kernel_call(&c,"GetModuleHandleExW",&result)&&!result&&!MR32(0x400)&&error==126);
MR32(c.esp)=4;assert(!hq_kernel_call(&c,"GetModuleHandleExW",&result));
MR32(c.esp)=0x1800000;MR32(c.esp+4)=0x300;MR32(c.esp+8)=100;
assert(hq_kernel_call(&c,"GetModuleFileNameW",&result)&&result==35);assert(MR16(0x300)=='C'&&MR16(0x300+result*2)==0);
MR32(c.esp)=0x700;MR32(c.esp+4)=4000;MR32(c.esp+8)=0;assert(hq_kernel_call(&c,"InitializeCriticalSectionEx",&result)&&result==1);
memset(g_mem+0x8ff,0xa5,70);MR32(c.esp)=0x900;
assert(hq_kernel_call(&c,"GetStartupInfoW",&result)&&MR32(0x900)==68&&MR32(0x904)==0&&MR8(0x8ff)==0xa5&&MR8(0x944)==0xa5);
MR32(c.esp)=0;MR32(c.esp+4)=1;MR32(c.esp+8)=0;MR32(c.esp+12)=0;assert(hq_kernel_call(&c,"CreateEventW",&result)&&result==0x70001000);
uint32_t values[]={0,1,0x400000,0x180ac70,0xf0000010,0xffffffff};
for(unsigned i=0;i<sizeof values/sizeof *values;i++){MR32(c.esp)=values[i];assert(hq_kernel_call(&c,"EncodePointer",&result));uint32_t encoded=result;
assert(hq_kernel_call(&c,"EncodePointer",&result)&&result==encoded);MR32(c.esp)=encoded;assert(hq_kernel_call(&c,"DecodePointer",&result)&&result==values[i]);}
MR16(0xa00)=0xe9;wide(0xa02,".ini");MR32(c.esp)=0xa00;assert(hq_kernel_call(&c,"CreateFileW",&result)&&result==0x12340000&&MR32(c.esp)==0xa00);
MR32(c.esp)=0xa00;MR32(c.esp+4)=64;MR32(c.esp+8)=0xb00;MR32(c.esp+12)=0xc00;
assert(hq_kernel_call(&c,"GetFullPathNameW",&result)&&result==14&&MR32(0xc00)==0xb12&&MR16(0xb12)==0xe9&&MR16(0xb1c)==0);
MR32(c.esp)=64;MR32(c.esp+4)=0xb00;assert(hq_kernel_call(&c,"GetCurrentDirectoryW",&result)&&result==8&&MR16(0xb00)=='C'&&MR16(0xb10)==0);
strcpy((char*)g_mem+0x600,"speed.exe");assert(hq_kernel_call(&c,"GetCommandLineW",&result)&&MR16(result)=='s');
assert(!memcmp(&c,&before,sizeof c));free(g_mem);}
''')
            result=subprocess.run(['clang','-O1','-Iruntime',str(source),'runtime/hq_kernel.c','-o',str(root/'kernel')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'kernel')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
