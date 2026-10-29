"""Exercise the real registry branch with the selected native WS configuration."""
from pathlib import Path
import unittest

from tests import test_widescreen as ws_tests


class RegistryDefaultTests(unittest.TestCase):
    def test_missing_only_defaults_preserve_saved_values_and_query_contract(self):
        source = Path('runtime/win32_ext.c').read_text()
        helpers = source[source.index('#define MAXREG '):source.index('/* GetTimeZoneInformation:')]
        registry = source[source.index('int win32_ext_call('):source.index('    /* --- window / USER32 --- */')]
        fragments = r'''
#include <unistd.h>
#include <strings.h>
#define ERROR_SUCCESS 0u
#define ERROR_FILE_NOT_FOUND 2u
#define OB_KEY 1
typedef struct {int kind;} Obj;
static uint32_t obj_new(int kind){assert(kind==OB_KEY);return 1;}
static Obj *obj_get(uint32_t handle){(void)handle;return NULL;}
static void obj_close(uint32_t handle){(void)handle;}
static uint32_t A(CPU *c,int i){return MR32(c->esp+4u*i);}
void mem_commit(uint32_t address,uint32_t size){assert(address+size<=0x1000000);}
uint8_t g_cbits[1u<<15];
const char *language_registry(void){return "English";}
''' + helpers + registry + '    else return 0;\n*out=r;return 1;\n}\n' + r'''
static uint32_t query(CPU *c,const char *name,uint32_t data,uint32_t cap){
 strcpy((char *)g_mem+0x2000,name);MR32(c->esp)=1;MR32(c->esp+4)=0x2000;
 MR32(c->esp+8)=0;MR32(c->esp+12)=0x2100;MR32(c->esp+16)=data;
 MR32(c->esp+20)=0x2104;MR32(0x2100)=0xdeadbeef;MR32(0x2104)=cap;
 CPU before=*c;uint32_t result=99;assert(win32_ext_call(c,"RegQueryValueExA",&result));
 assert(!memcmp(c,&before,sizeof *c));return result;
}
'''
        body = r'''
memset(g_cbits,255,sizeof g_cbits);setenv("NFSU2_REGFILE","registry",1);
FILE *file=fopen("registry","w");assert(file);
fputs("d g_CarEnvironmentMapEnable=0\ns g_VisualTreatment=saved\n",file);fclose(file);
CPU cpu={0},*c=&cpu;c->esp=0x1000;c->eax=42;c->cf=1;c->top=3;c->st[3]=1.25;
assert(query(c,"g_PerformanceLevel",0x2200,4)==2);assert(MR32(0x2104)==0);
ws_configure(".");assert(ws_patch_init());
assert(query(c,"G_CARENVIRONMENTMAPENABLE",0x2200,4)==0);
assert(MR32(0x2100)==4&&MR32(0x2104)==4&&MR32(0x2200)==0);
assert(query(c,"g_VisualTreatment",0x2200,16)==0);
assert(MR32(0x2100)==1&&!strcmp((char *)g_mem+0x2200,"saved"));
assert(query(c,"g_PerformanceLevel",0x2200,4)==(ENABLED?0:2));
if(ENABLED){
 assert(MR32(0x2100)==4&&MR32(0x2104)==4&&MR32(0x2200)==5);
 assert(query(c,"g_PerformanceLevel",0,0)==0&&MR32(0x2104)==4);
 MR32(0x2200)=0xabcdef;
 assert(query(c,"g_PerformanceLevel",0x2200,3)==234);
 assert(MR32(0x2104)==4&&MR32(0x2200)==0xabcdef);
 assert(query(c,"g_VSyncOn",0x2200,4)==0&&MR32(0x2200)==0);
}
assert(query(c,"unknown",0x2200,4)==2);
file=fopen("registry","r");assert(file);char contents[256]={0};fread(contents,1,255,file);fclose(file);
assert(!strcmp(contents,"d g_CarEnvironmentMapEnable=0\ns g_VisualTreatment=saved\n"));
win32_reg_put_dword("g_PerformanceLevel",2);
assert(query(c,"g_PerformanceLevel",0x2200,4)==0&&MR32(0x2200)==2);
'''
        for enabled in (0, 1):
            with self.subTest(enabled=enabled):
                ws_tests.WidescreenTests().run_native(
                    body.replace('ENABLED', str(enabled)),
                    f'[MISC]\nWriteSettingsToFile={enabled}\n', fragments=fragments)


if __name__ == '__main__':
    unittest.main()
