import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class AppPathTests(unittest.TestCase):
    def test_explicit_game_and_isolated_save_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();exe=root/'game'/'speed.exe';exe.parent.mkdir();exe.write_bytes(b'test')
            source=root/'test.c'
            source.write_text('''#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>
int app_prepare(const char *,char *,size_t,char *,size_t,char *,size_t);
int main(int argc,char **argv){(void)argc;char exe[4096],save[4096],reg[4096],before[4096],after[4096];
getcwd(before,sizeof before);assert(app_prepare(argv[1],exe,sizeof exe,save,sizeof save,reg,sizeof reg)==1);
getcwd(after,sizeof after);assert(!strcmp(before,after));assert(!strcmp(exe,argv[1]));assert(!strcmp(save,argv[2]));
assert(!strncmp(reg,save,strlen(save))&&!strcmp(reg+strlen(save),"/registry"));}
''')
            binary=root/'test';subprocess.run(['clang','-fobjc-arc',str(source),'runtime/app.m','runtime/launcher.m','-framework','Cocoa','-o',str(binary)],check=True,capture_output=True)
            env=os.environ.copy();env['NFSMW_SAVEDIR']=str(root/'Saves')
            subprocess.run([str(binary),str(exe),str(root/'Saves')],env=env,check=True,capture_output=True)
            self.assertTrue((root/'Saves').is_dir())
            env['NFSMW_SAVEDIR']='RelativeSaves'
            subprocess.run([str(binary),str(exe),str(root/'RelativeSaves')],env=env,cwd=root,check=True,capture_output=True)
            self.assertTrue((root/'RelativeSaves').is_dir())


if __name__=='__main__':unittest.main()
