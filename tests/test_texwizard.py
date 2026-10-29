from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest


HARNESS = r'''#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem;
static const char *root;
static unsigned calls;
int mw_texwizard_init(int);
int mw_texwizard_hook(CPU *,uint32_t);
void mw_texwizard_report(void);
int fileio_resolve_game(const char *win,char *out,size_t n){
 char rel[256];snprintf(rel,sizeof rel,"%s",win);
 for(char *s=rel;*s;s++)if(*s=='\\')*s='/';
 snprintf(out,n,"%s/%s",root,rel);FILE *f=fopen(out,"rb");if(!f)return 0;fclose(f);return 1;
}
uint32_t gheap_alloc(int heap,uint32_t n,int zero){assert(heap==1&&n<256&&!zero);return 0x8000;}
uint32_t call_guest(CPU *c,uint32_t fn,int n,const uint32_t *args){
 if(fn==0x65FD30){
  assert(n==5&&args[1]==1&&!args[2]&&!args[3]&&!args[4]);
  assert(!strcmp((char*)g_mem+args[0],"TEX\\ROCKPORT360\\textures.bin"));memset(c,0xa5,sizeof *c);calls++;return 0x5000;
 }
 assert(fn==0x6616F0&&n==2&&c->ecx==0x5000&&!args[0]&&!args[1]);memset(c,0x5a,sizeof *c);calls++;return 1;
}
void guest_hook(CPU *c,uint32_t ip){assert(mw_texwizard_hook(c,ip));}
'''


class TexWizardTests(unittest.TestCase):
    def run_native(self, root, body, extra=''):
        source = root / 'test.c'
        source.write_text(HARNESS + extra + '\nint main(int argc,char **argv){assert(argc==2);root=argv[1];'
                          'g_mem=calloc(1,0xA00000);CPU cpu={0},*c=&cpu;c->esp=0x1000;'
                          + body + '\nfree(g_mem);}\n')
        subprocess.run(['clang', '-O1', '-Iruntime', str(source),
                        'runtime/mw_texwizard.c', '-o', str(root / 'test')],
                       check=True, capture_output=True)
        return subprocess.run([str(root / 'test'), str(root)], check=True, capture_output=True)

    def pack(self, root, metadata):
        pack = root / 'TEX/ROCKPORT360'
        pack.mkdir(parents=True)
        (pack / 'meta.json').write_text(metadata)
        (pack / 'textures.bin').write_bytes(struct.pack('<II', 0xb3300000, 0))

    def test_comments_hashes_duplicates_and_pack_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.pack(root, '{"textures":[["A","_A"],// line comment\n'
                            '["B","_B"],/* block */["A","0x12345678"]]}')
            self.run_native(root, '''
assert(mw_texwizard_init(0));MR32(c->esp+4)=32;MR32(c->esp+8)=7;MR32(c->esp+12)=9;
assert(mw_texwizard_hook(c,0x503400)&&MR32(c->esp+4)==32);
assert(!mw_texwizard_hook(c,0x1234));
assert(mw_texwizard_init(1)==2);
CPU before=*c;assert(mw_texwizard_hook(c,0x6660C5));assert(!memcmp(c,&before,sizeof before));
assert(calls==2);assert(mw_texwizard_hook(c,0x6660C5)&&calls==2);
assert(mw_texwizard_hook(c,0x503400)&&MR32(c->esp+4)==0x12345678);
assert(MR32(c->esp+8)==7&&MR32(c->esp+12)==9);
MR32(c->esp+4)=33;assert(mw_texwizard_hook(c,0x503400)&&MR32(c->esp+4)==2112);
MR32(c->esp+4)=0xabcdef;assert(mw_texwizard_hook(c,0x503400)&&MR32(c->esp+4)==0xabcdef);
''')

    def test_invalid_metadata_cannot_leave_partial_mappings_active(self):
        for metadata in ('{"textures":[["A","_A"],["B",42]]}',
                         '{"textures":[["A","_A"]]}\0garbage'):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.pack(root, metadata)
                self.run_native(root, '''
assert(!mw_texwizard_init(1));MR32(c->esp+4)=32;
assert(mw_texwizard_hook(c,0x503400)&&MR32(c->esp+4)==32);
assert(mw_texwizard_hook(c,0x6660C5)&&calls==0);
''')

    @unittest.skipUnless(Path('game/speed.exe').is_file(), 'requires local supported executable')
    def test_lifted_lookup_returns_the_replacement_texture_pointer(self):
        from tools.lift import Lifter
        code, targets = Lifter('game/speed.exe', hooks=[0x503400]).lift(0x503400)
        stubs = ''.join(f'void sub_{a:08x}(CPU *c){{(void)c;assert(0);}}\n' for a in sorted(targets))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.pack(root, '{"textures":[["A","_A"]]}')
            result = self.run_native(root, '''
assert(mw_texwizard_init(1)==1);assert(mw_texwizard_hook(c,0x6660C5));
MR32(0x915198+2111%256*4)=0x6000;MR32(0x6000+0x24)=2111;
MR32(c->esp)=0xABCDEF;MR32(c->esp+4)=32;MR32(c->esp+8)=1;MR32(c->esp+12)=0;
sub_00503400(c);assert(c->eax==0x6000&&c->eip==0xABCDEF&&c->esp==0x1004);
assert(MR32(0x1008)==1&&!MR32(0x100C));mw_texwizard_report();
''', stubs + code)
            self.assertIn(b'1 confirmed replacement cache hits', result.stderr)


    @unittest.skipUnless(os.environ.get('NFSMW_HQ_PACK'), 'set NFSMW_HQ_PACK for the supplied pack integration test')
    def test_supplied_pack_configures_446_mappings_and_queues_real_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / 'TEX/ROCKPORT360'
            pack.parent.mkdir(parents=True)
            pack.symlink_to(Path(os.environ['NFSMW_HQ_PACK']).resolve(), target_is_directory=True)
            self.run_native(root, '''
assert(mw_texwizard_init(1)==446);assert(mw_texwizard_hook(c,0x6660C5)&&calls==2);
MR32(c->esp+4)=0x923db853;
assert(mw_texwizard_hook(c,0x503400)&&MR32(c->esp+4)==0x846f5e12);
''')


if __name__ == '__main__':
    unittest.main()
