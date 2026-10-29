from pathlib import Path
import subprocess
import tempfile
import unittest

class PluginLifecycleTests(unittest.TestCase):
    def test_catalog_tls_and_original_unlimiter_selection(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'plugin.c'
            source.write_text('''#include "hq_plugin.h"
#include <assert.h>
#include <stdlib.h>
static unsigned selected,attached;static int native=-1,original_selected;
int module_known_name(const char*n){assert(!strcmp(n,"nfsmwunlimiter.asi"));return original_selected;}
int module_static_tls(uint32_t base,uint32_t*data,uint32_t*size,uint32_t*index,uint32_t*slot){
 if(base==0x02000000)return 0;assert(base>=0x01000000&&base<=0x02400000);
 *data=base+0x100;*size=8;*index=base+0x200;*slot=128+selected++;return 1;}
int hq_tls_enable_slot(uint32_t data,uint32_t size,uint32_t index,uint32_t slot){assert(data+0x100==index&&size==8&&slot==127+selected);return 1;}
int hq_tls_attach(CPU*c){assert(c->eax==123);attached++;return 1;}
void mw_unlimiter_init(int value){native=value;}
int main(void){CPU c={0};c.eax=123;CPU before=c;
 assert(hq_plugin_module_mapped(&c,0x02000000)&&!selected&&!attached);
 unsigned bases[]={0x01000000,0x01400000,0x01800000,0x01c00000,0x02400000};
 for(unsigned i=0;i<5;i++)assert(hq_plugin_module_mapped(&c,bases[i]));
 assert(selected==5&&attached==5&&!memcmp(&before,&c,sizeof c));
 original_selected=0;hq_plugin_init_unlimiter(1);assert(native==1);
 original_selected=1;hq_plugin_init_unlimiter(1);assert(!native);
 hq_plugin_init_unlimiter(0);assert(!native);}
''')
            result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-Iruntime',str(source),'runtime/hq_plugin.c','-o',str(root/'plugin')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'plugin')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_eo_checkpoint_runs_after_original_callback_and_refuses_unknown_tuple(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'checkpoint.c'
            source.write_text('''#include "hq_plugin.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;static CPU after;static int known=1,captured;
void sub_01c04a50(CPU*);
void sub_01c04a50_body(CPU*c){c->eax=123;c->top=5;c->st[5]=1.25;POP32(c->eip);after=*c;}
int hq_checkpoint_known(unsigned point){assert(point==3);return known;}
void hq_prepare_checkpoint(CPU*c,unsigned point){(void)c;(void)point;}
void hq_capture(CPU*c,const char*name,uint32_t address){assert(!memcmp(c,&after,sizeof after));assert(!strcmp(name,"eohotkeys")&&address==0x01c04a50);captured++;}
int main(int argc,char**argv){(void)argv;known=argc==1;g_mem=calloc(1,0x1000);CPU c={0};c.esp=0x100;MR32(c.esp)=0xdeadbeef;
sub_01c04a50(&c);assert(known&&captured==1&&!memcmp(&c,&after,sizeof c));free(g_mem);}
''')
            result=subprocess.run(['clang','-O1','-Wl,-dead_strip','-Iruntime',str(source),'runtime/hq_plugin.c','-o',str(root/'checkpoint')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'checkpoint')],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(root/'checkpoint'),'unknown'],capture_output=True,text=True);self.assertEqual(result.returncode,78,result.stderr)
            self.assertIn('Unknown runtime patch tuple at checkpoint 3',result.stderr)

if __name__=='__main__':unittest.main()
