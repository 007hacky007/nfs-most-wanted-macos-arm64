from pathlib import Path
import subprocess
import tempfile
import unittest


class DispatchPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        source = Path('runtime/dispatch.c').read_text().split('/* A tail jump', 1)[0]
        source += '''
int g_efx_stat;
void (*g_backtrace_fn)(struct CPU*,int);
const uint32_t g_fn_addr[]={0};
const guest_fn g_fn_ptr[]={0};
const uint32_t g_fn_count=0;
void guest_backtrace(CPU*c,int n){(void)c;(void)n;}
static void first(CPU*c){c->eax=1;}
static void second(CPU*c){c->eax=2;}
int main(int argc,char**argv){
    (void)argc;CPU c={0};uint32_t base=TEXT_BASE+0x100;
    if(!strcmp(argv[1],"overflow")){
        for(unsigned i=0;i<129;i++)dispatch_patch(base+i,first);
        return 0;
    }
    unsigned count=!strcmp(argv[1],"replace")?1:128;
    if(!strcmp(argv[1],"before")){
        for(unsigned i=0;i<count;i++)dispatch_patch(base+i,first);
        dispatch_init();
    }else{
        dispatch_init();
        for(unsigned i=0;i<count;i++)dispatch_patch(base+i,first);
    }
    for(unsigned i=0;i<count;i++){
        guest_fn fn=g_dtab[base+i-TEXT_BASE];assert(fn);fn(&c);assert(c.eax==1);
    }
    if(!strcmp(argv[1],"replace")){
        const uint32_t dll=0x02001000;
        dispatch_patch(dll,first);dispatch_patch(dll,second);
        assert(patch_at(dll)==second);patch_at(dll)(&c);assert(c.eax==2);
        dispatch_patch(base,second);assert(patch_at(base)==second);
        g_dtab[base-TEXT_BASE](&c);assert(c.eax==2);
        /* Replacements must leave capacity available for distinct addresses. */
        for(unsigned i=0;i<200;i++)dispatch_patch(base,first);
        dispatch_patch(base+1000,second);
        g_dtab[base+1000-TEXT_BASE](&c);assert(c.eax==2);
    }
    return 0;
}
'''
        source = source.replace('#include "cpu.h"', '#include "cpu.h"\n#include <assert.h>', 1)
        path = root/'dispatch.c'; path.write_text(source)
        cls.binary = root/'dispatch'
        subprocess.run(['clang', '-O1', '-Iruntime', str(path), '-o', str(cls.binary)],
                       check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_more_than_24_patches_before_and_after_initialization(self):
        for mode in ('before', 'after'):
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.binary), mode], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_replacement_updates_game_and_dll_targets_without_consuming_capacity(self):
        result = subprocess.run([str(self.binary), 'replace'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_overflow_fails_explicitly(self):
        result = subprocess.run([str(self.binary), 'overflow'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('patch table full', result.stderr)


if __name__ == '__main__':
    unittest.main()
