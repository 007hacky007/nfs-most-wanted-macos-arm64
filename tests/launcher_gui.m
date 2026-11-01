#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#include <assert.h>

NSString *launcher_choose_game(void);

@interface TestPreferences : NSUserDefaults
@property NSMutableDictionary *values;
@end
@implementation TestPreferences
- (NSString *)stringForKey:(NSString *)key{return self.values[key];}
- (void)setObject:(id)value forKey:(NSString *)key{self.values[key]=value;}
- (void)removeObjectForKey:(NSString *)key{[self.values removeObjectForKey:key];}
@end
static TestPreferences *preferences;
static id isolated_preferences(id self,SEL command){(void)self;(void)command;return preferences;}

static void collect(NSView *view,NSMutableArray *views){
    for(NSView *child in view.subviews){[views addObject:child];collect(child,views);}
}

/* argv[1]: "bundled" (Resources/game is ready) or "missing"; argv[2]: screenshot path. */
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
            assert(!selected);
            puts("Launcher: missing bundled game explained, stale folders removed");
        }else{
            assert([selected isEqualToString:[game stringByAppendingPathComponent:@".nfsmw/full"]]);
            assert([preferences.values[@"GameMode"] isEqualToString:@"full"]);
            assert([preferences.values[@"Resolution"] isEqualToString:@"1920x1080"]);
            puts("Launcher: bundled game, all three modes, resolution persistence and Play passed");
        }
    }
    return 0;
}
