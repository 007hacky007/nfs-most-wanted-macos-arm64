from pathlib import Path
import subprocess
import tempfile
import unittest

class ImageTests(unittest.TestCase):
    def test_full_data_identity_keeps_canonical_code_image_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'test.c'
            source.write_text('''#include "hq_image.h"
#include <assert.h>
#include <string.h>
static int tampered;
int hq_image_hash(const char*p,const char*hash){
 if(!strcmp(p,"game/speed.exe"))return !strncmp(hash,"80774",5);
 if(!strcmp(p,"install/speed.exe"))return !strncmp(hash,"e801",4);
 if(!strcmp(p,"install/.nfsmw/full/speed.exe"))return !strncmp(hash,"8393",4);
 if(!strcmp(p,"install/.nfsmw/full/../runtime.exe")||!strcmp(p,"install/.nfsmw/runtime.exe"))return !tampered&&!strncmp(hash,"80774",5);
 return 0;
}
int app_runtime_image(const char*p,char*out,size_t n){if(strcmp(p,"install/speed.exe"))return 0;return snprintf(out,n,"install/.nfsmw/runtime.exe")<(int)n;}
int main(void){char out[128]="untouched";
assert(hq_image_select("game/speed.exe",out,sizeof out,0)&&!strcmp(out,"game/speed.exe"));
assert(hq_image_select("install/speed.exe",out,sizeof out,0)&&!strcmp(out,"install/.nfsmw/runtime.exe"));
strcpy(out,"untouched");assert(!hq_image_select("install/.nfsmw/full/speed.exe",out,sizeof out,0)&&!strcmp(out,"untouched"));
assert(hq_image_select("install/.nfsmw/full/speed.exe",out,sizeof out,1)&&!strcmp(out,"install/.nfsmw/full/../runtime.exe"));
tampered=1;strcpy(out,"untouched");assert(!hq_image_select("install/.nfsmw/full/speed.exe",out,sizeof out,1)&&!strcmp(out,"untouched"));
assert(!hq_image_select("unknown.exe",out,sizeof out,1));assert(!hq_image_select("game/speed.exe",out,4,1));}
''')
            subprocess.run(['clang','-O1','-include','stdio.h','-Iruntime',str(source),'runtime/hq_image.c','-o',str(root/'test')],check=True,capture_output=True)
            subprocess.run([str(root/'test')],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
