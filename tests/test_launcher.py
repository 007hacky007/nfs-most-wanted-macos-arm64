import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def test_packaged_game_is_selected_without_a_previous_development_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'Resources';bundled=resources/'game'
            bundled.mkdir(parents=True);(bundled/'speed.exe').write_bytes(b'test')
            external=root/'external';external.mkdir();(external/'speed.exe').write_bytes(b'test')
            source=root/'probe.m'
            source.write_text('''#import <Foundation/Foundation.h>
#include <assert.h>
NSString *launcher_game_folder(NSString *,NSString *,NSString *);
int main(int argc,char **argv){@autoreleasepool{
 NSString *r=@(argv[1]),*e=@(argv[2]),*old=@"obsolete-development-install";
 assert([launcher_game_folder(r,nil,old) isEqualToString:[r stringByAppendingPathComponent:@"game"]]);
 assert([launcher_game_folder(r,e,old) isEqualToString:e]);
 assert([launcher_game_folder(r,@"missing-external",old) isEqualToString:[r stringByAppendingPathComponent:@"game"]]);
 assert([launcher_game_folder(@"missing-resources",nil,old) isEqualToString:old]);
 }return 0;}
''')
            binary=root/'probe'
            subprocess.run(['clang','-fobjc-arc',str(source),'runtime/launcher.m',
                            '-framework','Cocoa','-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary),str(resources),str(external)],check=True,capture_output=True)

    @unittest.skipUnless(os.environ.get('NFSMW_TEST_GUI'), 'set NFSMW_TEST_GUI for the visible Cocoa launcher test')
    def test_visible_launcher_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            for folder in (game, game / '.nfsmw/visuals', game / '.nfsmw/full'):
                folder.mkdir(parents=True)
                (folder / 'speed.exe').write_bytes(b'test')
                (folder / 'd3dx9_26.dll').write_bytes(b'test')
            (game / 'install-manifest.json').write_text(json.dumps({'variants': {'visuals': {'ready': True}, 'full': {'ready': True}}}))
            binary = root / 'probe'
            subprocess.run(['clang', '-fobjc-arc', '-DNFS_HQ_MODULES=1', 'tests/launcher_gui.m', 'runtime/launcher.m', '-framework', 'Cocoa', '-o', str(binary)], check=True, capture_output=True)
            capture = Path('out/launcher.png').resolve()
            capture.parent.mkdir(exist_ok=True)
            subprocess.run([str(binary), str(game), str(capture)], check=True, timeout=30, capture_output=True)
            self.assertTrue(capture.is_file())

    def test_resolution_mode_validation_and_profile_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            game.mkdir()
            (game / 'speed.exe').write_bytes(b'test')
            (game / 'd3dx9_26.dll').write_bytes(b'test')
            (game / 'install-manifest.json').write_text(json.dumps({'variants': {'visuals': {'ready': True}, 'full': {'ready': True}}}))
            visual = game / '.nfsmw/visuals'
            visual.mkdir(parents=True)
            (visual / 'speed.exe').write_bytes(b'test')
            (visual / 'd3dx9_26.dll').write_bytes(b'test')
            full = game / '.nfsmw/full'
            full.mkdir()
            (full / 'speed.exe').write_bytes(b'test')
            (full / 'd3dx9_26.dll').write_bytes(b'test')
            source = root / 'probe.m'
            source.write_text('''#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>
int launcher_options(const char *,const char *,const char *,char *,size_t,char *,size_t);
int main(int argc,char **argv){@autoreleasepool{
 char selected[4096],error[1024];
 assert(launcher_options(argv[1],"standard","1920x1080",selected,sizeof selected,error,sizeof error));
 assert(!strcmp(selected,argv[1]));assert(!strcmp(getenv("NFSRES"),"1920x1080"));
 assert(!launcher_options(argv[1],"standard","1920x1080junk",selected,sizeof selected,error,sizeof error));
 assert(!launcher_options(argv[1],"standard","8193x1080",selected,sizeof selected,error,sizeof error));
 assert(!launcher_options(argv[1],"other","1280x720",selected,sizeof selected,error,sizeof error));
 assert(launcher_options(argv[1],"full","1280x720",selected,sizeof selected,error,sizeof error));
 assert(strstr(selected,"/.nfsmw/full"));assert(!strcmp(getenv("NFSMW_MODE"),"full"));
 assert(launcher_options(argv[1],"visuals","1280x720",selected,sizeof selected,error,sizeof error));
 assert(strstr(selected,"/.nfsmw/visuals"));assert(!strcmp(getenv("NFSMW_MODE"),"visuals"));
 }return 0;}
''')
            binary = root / 'probe'
            subprocess.run(['clang', '-fobjc-arc', '-DNFS_HQ_MODULES=1', str(source), 'runtime/launcher.m', '-framework', 'Cocoa', '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary), str(game)], check=True, capture_output=True)

    def test_hq_runtime_image_is_found_beside_selected_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            (game / '.nfsmw').mkdir(parents=True)
            image = game / '.nfsmw/runtime.exe'
            image.write_bytes(b'known image is verified by main')
            source = root / 'probe.c'
            source.write_text('''#include <assert.h>
#include <stddef.h>
#include <string.h>
int app_runtime_image(const char *,char *,size_t);
int main(int argc,char **argv){char image[4096];assert(app_runtime_image(argv[1],image,sizeof image));assert(!strcmp(image,argv[2]));}
''')
            binary = root / 'probe'
            subprocess.run(['clang', '-fobjc-arc', str(source), 'runtime/app.m', 'runtime/launcher.m', '-framework', 'Cocoa', '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary), str(game / 'speed.exe'), str(image)], check=True, capture_output=True)
