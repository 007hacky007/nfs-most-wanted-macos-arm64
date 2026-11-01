#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#include <assert.h>

NSString *launcher_choose_game(void);
typedef void (^LauncherFetch)(NSURLRequest *,void (^)(NSData *));
extern LauncherFetch launcher_update_fetch;

@interface TestPreferences : NSUserDefaults
@property NSMutableDictionary *values;
@end
@implementation TestPreferences
- (id)objectForKey:(NSString *)key{return self.values[key];}
- (NSString *)stringForKey:(NSString *)key{return self.values[key];}
- (void)setObject:(id)value forKey:(NSString *)key{self.values[key]=value;}
- (void)removeObjectForKey:(NSString *)key{[self.values removeObjectForKey:key];}
@end
static TestPreferences *preferences;
static id isolated_preferences(id self,SEL command){(void)self;(void)command;return preferences;}

static void collect(NSView *view,NSMutableArray *views){
    for(NSView *child in view.subviews){[views addObject:child];collect(child,views);}
}

/* argv[1]: "bundled" (Resources/game is ready) or "missing"; argv[2]: screenshot path.
 * The probe is linked with an Info.plist stamped NFSBuilderVersion 0.3.6, and the update
 * check gets a fake GitHub reply offering 9.9.9; nothing goes to the network. */
int main(int argc,char **argv){
    @autoreleasepool{
        assert(argc==3);
        BOOL missing=!strcmp(argv[1],"missing");
        NSString *capture=[NSString stringWithUTF8String:argv[2]];
        NSString *game=[NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"game"];
        preferences=[TestPreferences new];
        preferences.values=[@{@"GameFolder":@"/obsolete/game",@"ExternalGameFolder":@"/obsolete/external",
                              @"GameMode":@"full",@"Resolution":@"1920x1080"} mutableCopy];
        method_setImplementation(class_getClassMethod(NSUserDefaults.class,@selector(standardUserDefaults)),(IMP)isolated_preferences);
        [NSApplication sharedApplication];
        __block NSUInteger requests=0;
        launcher_update_fetch=^(NSURLRequest *request,void (^done)(NSData *)){
            requests++;assert([[request valueForHTTPHeaderField:@"User-Agent"] isEqualToString:@"NFSMW-Launcher"]);
            NSString *base=@"https://github.com/007hacky007/nfs-most-wanted-macos-arm64/releases";
            done([NSJSONSerialization dataWithJSONObject:@{@"tag_name":@"v9.9.9",@"html_url":[base stringByAppendingString:@"/tag/v9.9.9"],
                @"assets":@[@{@"name":@"NFSMW-Builder.dmg",@"browser_download_url":[base stringByAppendingString:@"/download/v9.9.9/NFSMW-Builder.dmg"]}]}
                options:0 error:nil]);
        };
        __block BOOL checked=NO;
        NSTimer *timer=[NSTimer timerWithTimeInterval:.5 repeats:NO block:^(NSTimer *unused){
            (void)unused;
            NSWindow *window=NSApp.modalWindow;
            assert(window.visible);
            NSMutableArray *views=[NSMutableArray array];collect(window.contentView,views);
            if(missing){
                BOOL explained=NO;
                for(NSView *view in views)
                    if([view isKindOfClass:NSTextField.class]&&[((NSTextField *)view).stringValue containsString:@"Build the app again with NFSMW Builder"])explained=YES;
                assert(explained);checked=YES;
                [NSApp stopModalWithCode:NSAlertFirstButtonReturn];return;
            }
            assert([window.title isEqualToString:@"Most Wanted Launcher"]);
            NSPopUpButton *mode=nil,*resolution=nil;NSButton *play=nil;
            for(NSView *view in views){
                if([view isKindOfClass:NSPopUpButton.class]){
                    NSPopUpButton *popup=(NSPopUpButton *)view;
                    if(popup.numberOfItems==3)mode=popup;else resolution=popup;
                }else if([view isKindOfClass:NSButton.class]){
                    NSString *title=((NSButton *)view).title;
                    assert(![title hasPrefix:@"Choose"]);
                    if([title isEqualToString:@"Play"])play=(NSButton *)view;
                }else if([view isKindOfClass:NSTextField.class])
                    assert(![((NSTextField *)view).stringValue isEqualToString:@"Game files"]);
            }
            assert(mode&&resolution&&play&&play.enabled);
            NSButton *updates=nil,*notNow=nil;NSTextField *offer=nil;
            for(NSView *view in views){
                if([view isKindOfClass:NSButton.class]&&[((NSButton *)view).title isEqualToString:@"Check for updates"])updates=(NSButton *)view;
                if([view isKindOfClass:NSButton.class]&&[((NSButton *)view).title isEqualToString:@"Not now"])notNow=(NSButton *)view;
                if([view isKindOfClass:NSTextField.class]&&[((NSTextField *)view).stringValue hasPrefix:@"NFSMW Builder 9.9.9"])offer=(NSTextField *)view;
            }
            assert(updates&&updates.enabled&&updates.state==NSControlStateValueOn);
            assert(requests==1&&offer&&!offer.hiddenOrHasHiddenAncestor&&notNow);
            assert([offer.stringValue isEqualToString:@"NFSMW Builder 9.9.9 is available"]);
            [notNow performClick:nil];
            assert(offer.hiddenOrHasHiddenAncestor&&[preferences.values[@"DismissedUpdateVersion"] isEqualToString:@"9.9.9"]);
            [updates performClick:nil];
            assert([preferences.values[@"CheckForUpdates"] isEqual:@NO]&&requests==1);
            [updates performClick:nil];
            assert([preferences.values[@"CheckForUpdates"] isEqual:@YES]&&requests==1);
            assert(([mode.itemTitles isEqualToArray:@[@"Standard",@"HQ visuals only",@"HQ full mod"]]));
            assert([resolution.titleOfSelectedItem isEqualToString:@"1920x1080"]);
            for(NSString *title in mode.itemTitles){
                [mode selectItemWithTitle:title];
                [NSApp sendAction:mode.action to:mode.target from:mode];assert(play.enabled);
            }
            [window displayIfNeeded];
            NSBitmapImageRep *bitmap=[window.contentView bitmapImageRepForCachingDisplayInRect:window.contentView.bounds];
            [window.contentView cacheDisplayInRect:window.contentView.bounds toBitmapImageRep:bitmap];
            NSData *png=[bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
            assert([png writeToFile:capture atomically:YES]);
            checked=YES;[play performClick:nil];
        }];
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSModalPanelRunLoopMode];
        NSString *selected=launcher_choose_game();
        assert(checked);
        assert(!preferences.values[@"GameFolder"]&&!preferences.values[@"ExternalGameFolder"]);
        if(missing){
            assert(!selected&&requests==0);
            puts("Launcher: missing bundled game explained, stale folders removed");
        }else{
            assert([selected isEqualToString:[game stringByAppendingPathComponent:@".nfsmw/full"]]);
            assert([preferences.values[@"GameMode"] isEqualToString:@"full"]);
            assert([preferences.values[@"Resolution"] isEqualToString:@"1920x1080"]);
            assert(requests==1&&[preferences.values[@"LastUpdateCheck"] isKindOfClass:NSDate.class]);
            puts("Launcher: bundled game, update notice, all three modes, resolution persistence and Play passed");
        }
    }
    return 0;
}
