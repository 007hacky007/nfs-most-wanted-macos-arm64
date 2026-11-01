import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def test_only_the_game_inside_the_app_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);resources=root/'Resources';bundled=resources/'game'
            bundled.mkdir(parents=True);(bundled/'speed.exe').write_bytes(b'test')
            partial=root/'Partial';(partial/'game').mkdir(parents=True);(partial/'game/speed.exe').write_bytes(b'test')
            (bundled/'d3dx9_26.dll').write_bytes(b'test')
            broken=root/'Broken';(broken/'game/speed.exe').mkdir(parents=True);(broken/'game/d3dx9_26.dll').write_bytes(b'test')
            source=root/'probe.m'
            source.write_text('''#import <Foundation/Foundation.h>
#include <assert.h>
NSString *launcher_game_folder(NSString *);
int main(int argc,char **argv){@autoreleasepool{
 NSString *r=@(argv[1]);
 assert([launcher_game_folder(r) isEqualToString:[r stringByAppendingPathComponent:@"game"]]);
 assert(!launcher_game_folder(@(argv[2])));
 assert(!launcher_game_folder(@(argv[3])));
 assert(!launcher_game_folder(@"missing-resources"));
 assert(!launcher_game_folder(nil));
 }return 0;}
''')
            binary=root/'probe'
            subprocess.run(['clang','-fobjc-arc',str(source),'runtime/launcher.m',
                            '-framework','Cocoa','-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary),str(resources),str(partial),str(broken)],check=True,capture_output=True)

    def test_update_check_gate_request_and_offer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'probe.m'
            source.write_text(r'''#import <Foundation/Foundation.h>
#include <assert.h>
int launcher_compare_versions(NSString *,NSString *);
BOOL launcher_update_due(NSUserDefaults *,NSDate *);
BOOL launcher_check_for_updates(NSUserDefaults *,NSString *,NSDate *,void (^)(NSDictionary *));
NSDictionary *launcher_update_offer(NSData *,NSString *,NSString *);
typedef void (^LauncherFetch)(NSURLRequest *,void (^)(NSData *));
extern LauncherFetch launcher_update_fetch;
@interface Prefs : NSUserDefaults
@property NSMutableDictionary *values;
@end
@implementation Prefs
- (id)objectForKey:(NSString *)key{return self.values[key];}
- (NSString *)stringForKey:(NSString *)key{return self.values[key];}
- (void)setObject:(id)value forKey:(NSString *)key{self.values[key]=value;}
@end
static NSData *release(NSString *tag,NSString *page,NSString *asset,NSString *url){
    return [NSJSONSerialization dataWithJSONObject:@{@"tag_name":tag,@"html_url":page,
        @"assets":@[@{@"name":@"NFSMW-Builder.dmg.sha256",@"browser_download_url":@"https://github.com/o/r/x.sha256"},
                    @{@"name":asset,@"browser_download_url":url}]} options:0 error:nil];
}
int main(void){@autoreleasepool{
    assert(launcher_compare_versions(@"0.4.0",@"0.3.6")>0);assert(launcher_compare_versions(@"0.10.0",@"0.9.9")>0);
    assert(launcher_compare_versions(@"1.0",@"1.0.0")==0);assert(launcher_compare_versions(@"0.4.0-dev",@"0.4.0")==0);
    assert(launcher_compare_versions(@"1.2",@"1.10")<0);
    NSDate *now=[NSDate dateWithTimeIntervalSince1970:2000000000];
    Prefs *prefs=[Prefs new];prefs.values=[NSMutableDictionary dictionary];
    assert(launcher_update_due(prefs,now));
    prefs.values[@"LastUpdateCheck"]=[now dateByAddingTimeInterval:-23*3600];assert(!launcher_update_due(prefs,now));
    prefs.values[@"LastUpdateCheck"]=[now dateByAddingTimeInterval:-25*3600];assert(launcher_update_due(prefs,now));
    prefs.values[@"LastUpdateCheck"]=[now dateByAddingTimeInterval:3600];assert(launcher_update_due(prefs,now));
    NSString *page=@"https://github.com/007hacky007/nfs-most-wanted-macos-arm64/releases/tag/v0.4.0";
    NSString *dmg=@"https://github.com/007hacky007/nfs-most-wanted-macos-arm64/releases/download/v0.4.0/NFSMW-Builder.dmg";
    NSData *good=release(@"v0.4.0",page,@"NFSMW-Builder.dmg",dmg);
    assert([launcher_update_offer(good,@"0.3.6",nil) isEqualToDictionary:(@{@"version":@"0.4.0",@"notes":page,@"download":dmg})]);
    assert(launcher_update_offer(release(@"0.4.0",page,@"NFSMW-Builder.dmg",dmg),@"0.3.6",nil));
    assert(!launcher_update_offer(good,@"0.4.0",nil));assert(!launcher_update_offer(good,@"0.5.0",nil));
    assert(!launcher_update_offer(good,@"0.3.6",@"0.4.0"));assert(launcher_update_offer(good,@"0.3.6",@"0.3.9"));
    assert(!launcher_update_offer(good,nil,nil));assert(!launcher_update_offer(nil,@"0.3.6",nil));
    assert(!launcher_update_offer([@"not json" dataUsingEncoding:NSUTF8StringEncoding],@"0.3.6",nil));
    assert(!launcher_update_offer(release(@"v0.4.0",page,@"Other.dmg",dmg),@"0.3.6",nil));
    assert(!launcher_update_offer(release(@"v0.4.0",page,@"NFSMW-Builder.dmg",@"http://github.com/x.dmg"),@"0.3.6",nil));
    assert(!launcher_update_offer(release(@"v0.4.0",page,@"NFSMW-Builder.dmg",@"https://example.com/x.dmg"),@"0.3.6",nil));
    assert(!launcher_update_offer(release(@"v0.4.0",@"https://example.com/",@"NFSMW-Builder.dmg",dmg),@"0.3.6",nil));
    assert(!launcher_update_offer(release(@"vnext",page,@"NFSMW-Builder.dmg",dmg),@"0.3.6",nil));
    __block NSMutableArray *requests=[NSMutableArray array];__block NSData *reply=good;
    launcher_update_fetch=^(NSURLRequest *request,void (^done)(NSData *)){[requests addObject:request];done(reply);};
    prefs.values=[@{@"CheckForUpdates":@NO} mutableCopy];
    assert(!launcher_check_for_updates(prefs,@"0.3.6",now,^(NSDictionary *o){(void)o;assert(0);}));
    prefs.values=[NSMutableDictionary dictionary];
    assert(!launcher_check_for_updates(prefs,nil,now,^(NSDictionary *o){(void)o;assert(0);}));
    assert(requests.count==0&&!prefs.values[@"LastUpdateCheck"]);
    __block NSDictionary *offered=nil;
    assert(launcher_check_for_updates(prefs,@"0.3.6",now,^(NSDictionary *o){assert(NSThread.isMainThread);offered=o;}));
    NSDate *limit=[NSDate dateWithTimeIntervalSinceNow:5];
    while(!offered&&[limit timeIntervalSinceNow]>0)[NSRunLoop.mainRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:.05]];
    assert([offered[@"version"] isEqualToString:@"0.4.0"]);
    NSURLRequest *request=requests[0];
    assert([request.URL.absoluteString isEqualToString:@"https://api.github.com/repos/007hacky007/nfs-most-wanted-macos-arm64/releases/latest"]);
    assert([request.HTTPMethod isEqualToString:@"GET"]&&request.timeoutInterval==5&&!request.HTTPShouldHandleCookies&&!request.HTTPBody);
    assert([[request.allHTTPHeaderFields.allKeys sortedArrayUsingSelector:@selector(compare:)] isEqualToArray:(@[@"Accept",@"Accept-Language",@"User-Agent"])]);
    assert([[request valueForHTTPHeaderField:@"User-Agent"] isEqualToString:@"NFSMW-Launcher"]);
    assert([prefs.values[@"LastUpdateCheck"] isEqual:now]);
    assert(!launcher_check_for_updates(prefs,@"0.3.6",[now dateByAddingTimeInterval:3600],^(NSDictionary *o){(void)o;assert(0);}));
    assert(requests.count==1);
    reply=nil;prefs.values=[NSMutableDictionary dictionary];
    assert(launcher_check_for_updates(prefs,@"0.3.6",now,^(NSDictionary *o){(void)o;assert(0);}));
    [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.2]];
    assert(requests.count==2);
    puts("update check ok");
}return 0;}
''')
            binary=root/'probe'
            subprocess.run(['clang','-fobjc-arc',str(source),'runtime/launcher.m','-framework','Cocoa','-o',str(binary)],
                           check=True,capture_output=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('update check ok',result.stdout)

    def test_launcher_has_no_folder_chooser_or_saved_game_path(self):
        source=Path('runtime/launcher.m').read_text()
        for gone in ('NSOpenPanel','chooseFolder','Choose...','setObject:self.folder'):
            self.assertNotIn(gone,source)
        self.assertIn('removeObjectForKey:@"GameFolder"',source)
        self.assertIn('removeObjectForKey:@"ExternalGameFolder"',source)

    @unittest.skipUnless(os.environ.get('NFSMW_TEST_GUI'), 'set NFSMW_TEST_GUI for the visible Cocoa launcher test')
    def test_visible_launcher_controls(self):
        # Outside a bundle NSBundle.mainBundle.resourcePath is the probe's folder, so root/game
        # stands in for Contents/Resources/game.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            for folder in (game, game / '.nfsmw/visuals', game / '.nfsmw/full'):
                folder.mkdir(parents=True)
                (folder / 'speed.exe').write_bytes(b'test')
                (folder / 'd3dx9_26.dll').write_bytes(b'test')
            (game / 'install-manifest.json').write_text(json.dumps({'variants': {'visuals': {'ready': True}, 'full': {'ready': True}}}))
            binary = root / 'probe'
            info = root / 'Info.plist'
            info.write_bytes(plistlib.dumps({'CFBundleIdentifier': 'local.nfsmw.launcher-test', 'NFSBuilderVersion': '0.3.6'}))
            subprocess.run(['clang', '-fobjc-arc', '-DNFS_HQ_MODULES=1', 'tests/launcher_gui.m', 'runtime/launcher.m', '-framework', 'Cocoa',
                            '-sectcreate', '__TEXT', '__info_plist', str(info), '-o', str(binary)], check=True, capture_output=True)
            capture = Path('out/launcher.png').resolve()
            capture.parent.mkdir(exist_ok=True)
            subprocess.run([str(binary), 'bundled', str(capture)], check=True, timeout=30, capture_output=True)
            self.assertTrue(capture.is_file())

    @unittest.skipUnless(os.environ.get('NFSMW_TEST_GUI'), 'set NFSMW_TEST_GUI for the visible Cocoa launcher test')
    def test_missing_bundled_game_explains_and_quits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'game').mkdir()
            (root / 'game/d3dx9_26.dll').write_bytes(b'test')
            binary = root / 'probe'
            subprocess.run(['clang', '-fobjc-arc', '-DNFS_HQ_MODULES=1', 'tests/launcher_gui.m', 'runtime/launcher.m', '-framework', 'Cocoa', '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary), 'missing', str(root / 'unused.png')], check=True, timeout=30, capture_output=True)

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
