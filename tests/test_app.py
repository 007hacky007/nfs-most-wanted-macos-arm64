import os
import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest


class AppPathTests(unittest.TestCase):
    def test_launcher_restarts_engine_without_reusing_cocoa_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();bundle=root/'Test.app';contents=bundle/'Contents'
            binary=contents/'MacOS/Test';binary.parent.mkdir(parents=True)
            (contents/'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleExecutable':'Test','CFBundleIdentifier':'local.nfsmw.restart-test',
                'CFBundlePackageType':'APPL'}))
            game=root/'game files';game.mkdir();exe=game/'speed.exe';exe.write_bytes(b'test')
            source=root/'test.m'
            source.write_text('''#import <Cocoa/Cocoa.h>
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int app_prepare(const char *,char *,size_t,char *,size_t,char *,size_t);
FILE *freopen(const char *path,const char *mode,FILE *stream){return stream;}
static int launcher_was_used;
NSString *launcher_choose_game(void){
 launcher_was_used=1;
 setenv("NFSRES","1920x1080",1);setenv("NFSMW_MODE","visuals",1);
 char pid[32];snprintf(pid,sizeof pid,"%d",getpid());setenv("TEST_LAUNCHER_PID",pid,1);
 return @(getenv("TEST_GAME_FOLDER"));
}
int main(int argc,char **argv){@autoreleasepool{
 char exe[4096],save[4096],reg[4096];
 if(argc==1){
  app_prepare(NULL,exe,sizeof exe,save,sizeof save,reg,sizeof reg);
  assert(!"launcher returned into the old engine process image");
 }
 assert(argc==2&&!launcher_was_used&&NSApp==nil);
 assert(atoi(getenv("TEST_LAUNCHER_PID"))==getpid());
 assert(!strcmp(getenv("NFSRES"),"1920x1080"));
 assert(!strcmp(getenv("NFSMW_MODE"),"visuals"));
 assert(app_prepare(argv[1],exe,sizeof exe,save,sizeof save,reg,sizeof reg)==1);
 assert(!strcmp(exe,argv[1])&&!strcmp(save,getenv("NFSMW_SAVEDIR")));
 assert([@(exe) isEqualToString:[@(getenv("TEST_GAME_FOLDER")) stringByAppendingPathComponent:@"speed.exe"]]);
 return 0;
}}
''')
            subprocess.run(['clang','-fobjc-arc',str(source),'runtime/app.m',
                            '-framework','Cocoa','-o',str(binary)],check=True,capture_output=True)
            env=os.environ.copy();env['TEST_GAME_FOLDER']=str(game);env['NFSMW_SAVEDIR']=str(root/'Saves')
            result=subprocess.run([str(binary)],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)

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
