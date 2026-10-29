from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.hq_module_catalog import MODULES,render_c_catalog

class ModuleRuntimeTests(unittest.TestCase):
    def test_catalog_namespaces_and_static_tls_work_with_optional_modules(self):
        declarations=['#include "cpu.h"','#include "module.h"','#include <assert.h>',
                      'typedef struct {uint32_t iat;const char*dll,*name;int nargs;} ImpEnt;',
                      'const uint32_t g_imp_count=5;','static void body(CPU*c){(void)c;}']
        for i,module in enumerate(MODULES):
            prefix='g_'+module.prefix
            declarations += [f'const uint32_t {prefix}imp_count={i+2};',f'const ImpEnt {prefix}imp[{i+2}]={{0}};',
                f'const uint32_t {prefix}fn_count=1,{prefix}fn_addr[]={{0x{module.base+0x1000:x}}};',
                f'const mod_fn {prefix}fn_ptr[]={{body}};',
                f'const ModInfo {prefix}modinfo={{.name="{Path(module.path).name.lower()}",.base=0x{module.base:x},.text=0x{module.base+0x1000:x},.text_size=0x1000}};']
        main='''int main(void){assert(module_count()==EXPECTED);uint32_t index=5;
for(uint32_t i=0;i<5;i++)assert(module_of_import(i)==0);
for(int id=1;id<=EXPECTED;id++){uint32_t count=99;const void*imports=module_imports(id,&count);assert(imports&&count==(unsigned)id+1&&module_imp_first(id)==index);
 for(unsigned j=0;j<count;j++)assert(module_of_import(index+j)==id);index+=count;}
assert(module_of_import(index)==-1&&module_imp_first(EXPECTED+1)==UINT32_MAX);
uint32_t n=99;assert(!module_imports(0,&n)&&n==0);uint32_t data=7,size=7,address=7,slot=7;
assert(!module_static_tls(0x02000000,&data,&size,&address,&slot)&&data==7&&slot==7);
#if NFS_HQ_MODULES
assert(module_static_tls(0x01000000,&data,&size,&address,&slot)&&data==0x01020748&&size==8&&address==0x0102f644&&slot==128);
assert(module_static_tls(0x02400000,&data,&size,&address,&slot)&&data==0x024108d8&&size==8&&address==0x02413744&&slot==132);
#else
assert(!module_static_tls(0x01000000,&data,&size,&address,&slot));
#endif
}
'''
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'catalog.inc').write_text(render_c_catalog(MODULES))
            for enabled in (0,1):
                source=root/f'test{enabled}.c';source.write_text('\n'.join(declarations)+'\n'+main.replace('EXPECTED','6'if enabled else'1'))
                result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-Iruntime','-I'+str(root),f'-DNFS_HQ_MODULES={enabled}',str(source),'runtime/module.c','-o',str(root/f'test{enabled}')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                result=subprocess.run([str(root/f'test{enabled}')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
