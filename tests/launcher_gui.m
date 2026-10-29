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
@end
static TestPreferences *preferences;
static id isolated_preferences(id self,SEL command){(void)self;(void)command;return preferences;}

int main(int argc,char **argv){
    @autoreleasepool{
        assert(argc==3);
        NSString *folder=[NSString stringWithUTF8String:argv[1]];
        NSString *capture=[NSString stringWithUTF8String:argv[2]];
        preferences=[TestPreferences new];
        preferences.values=[@{@"GameFolder":folder,@"GameMode":@"full",@"Resolution":@"1920x1080"} mutableCopy];
        method_setImplementation(class_getClassMethod(NSUserDefaults.class,@selector(standardUserDefaults)),(IMP)isolated_preferences);
        [NSApplication sharedApplication];
        NSTimer *timer=[NSTimer timerWithTimeInterval:.5 repeats:NO block:^(NSTimer *unused){
            (void)unused;
            NSWindow *window=NSApp.modalWindow;
            assert(window.visible&&[window.title isEqualToString:@"Most Wanted Launcher"]);
            NSPopUpButton *mode=nil,*resolution=nil;NSButton *play=nil;
            for(NSView *view in window.contentView.subviews){
                if([view isKindOfClass:NSPopUpButton.class]){
                    NSPopUpButton *popup=(NSPopUpButton *)view;
                    if(popup.numberOfItems==3)mode=popup;else resolution=popup;
                }else if([view isKindOfClass:NSButton.class]&&[((NSButton *)view).title isEqualToString:@"Play"])play=(NSButton *)view;
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
            [play performClick:nil];
        }];
        [NSRunLoop.mainRunLoop addTimer:timer forMode:NSModalPanelRunLoopMode];
        NSString *selected=launcher_choose_game();
        assert([selected isEqualToString:[folder stringByAppendingPathComponent:@".nfsmw/full"]]);
        assert([preferences.values[@"GameMode"] isEqualToString:@"full"]);
        assert([preferences.values[@"Resolution"] isEqualToString:@"1920x1080"]);
        puts("Launcher: all three modes, resolution persistence and Play passed");
    }
    return 0;
}
