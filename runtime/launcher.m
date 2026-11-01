#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int app_full_hq_supported(void){
#if NFS_HQ_MODULES
    return 1;
#else
    return 0;
#endif
}

/* The game always runs from the copy inside the app: Contents/Resources/game. */
NSString *launcher_game_folder(NSString *resources){
    if(!resources.length)return nil;
    NSString *bundled=[resources stringByAppendingPathComponent:@"game"];
    for(NSString *name in @[@"speed.exe",@"d3dx9_26.dll"]){
        BOOL directory=NO;
        if(![NSFileManager.defaultManager fileExistsAtPath:[bundled stringByAppendingPathComponent:name] isDirectory:&directory]||directory)
            return nil;
    }
    return bundled;
}

static NSString *const missing_game=@"The game files inside NFSMW.app are missing or damaged. "
    "Build the app again with NFSMW Builder.";

int launcher_options(const char *folder,const char *mode,const char *resolution,
                     char *selected,size_t selected_size,char *error,size_t error_size){
    @autoreleasepool{
        NSString *problem=nil;
        NSString *root=folder?[NSString stringWithUTF8String:folder]:nil;
        NSString *choice=mode?[NSString stringWithUTF8String:mode]:nil;
        unsigned w=0,h=0;char tail=0;
        if(!root.length)problem=missing_game;
        if(!resolution||sscanf(resolution,"%ux%u%c",&w,&h,&tail)!=2||w<640||h<480||w>8192||h>8192)
            problem=@"Choose a resolution between 640x480 and 8192x8192.";
        if(![@[@"standard",@"visuals",@"full"] containsObject:choice])problem=@"Unknown game mode.";
        if([choice isEqualToString:@"full"]&&!app_full_hq_supported())problem=@"HQ full mod is unavailable in this build.";
        NSFileManager *files=NSFileManager.defaultManager;
        if(!problem&&![choice isEqualToString:@"standard"]){
            NSData *data=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"install-manifest.json"]];
            NSDictionary *manifest=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
            NSDictionary *variants=[manifest isKindOfClass:NSDictionary.class]?manifest[@"variants"]:nil;
            NSDictionary *variant=[variants isKindOfClass:NSDictionary.class]?variants[choice]:nil;
            if(![variant isKindOfClass:NSDictionary.class]||![variant[@"ready"] isEqual:@YES])
                problem=[NSString stringWithFormat:@"HQ %@ is unavailable for this installation.",
                         [choice isEqualToString:@"full"]?@"full mod":@"visuals"];
            root=[root stringByAppendingPathComponent:[@".nfsmw" stringByAppendingPathComponent:choice]];
        }
        if(!problem){
            for(NSString *name in @[@"speed.exe",@"d3dx9_26.dll"]){
                BOOL directory=NO;
                if(![files fileExistsAtPath:[root stringByAppendingPathComponent:name] isDirectory:&directory]||directory){
                    problem=missing_game;break;
                }
            }
        }
        if(!problem&&root.length){
            int n=snprintf(selected,selected_size,"%s",root.fileSystemRepresentation);
            if(n<0||(size_t)n>=selected_size)problem=@"The installation path is too long.";
        }else if(!problem)problem=missing_game;
        if(problem){snprintf(error,error_size,"%s",problem.UTF8String);return 0;}
        char value[32];snprintf(value,sizeof value,"%ux%u",w,h);
        setenv("NFSRES",value,1);setenv("NFSMW_MODE",mode,1);
        if(error_size)error[0]=0;
        return 1;
    }
}

@interface MWLauncher : NSObject <NSWindowDelegate>
@property NSWindow *window;
@property NSTextField *status;
@property NSPopUpButton *resolution,*mode;
@property NSButton *playButton;
@property NSString *folder,*selected;
@end

@implementation MWLauncher
- (void)refresh{
    NSArray *modes=@[@"standard",@"visuals",@"full"];
    char selected[4096],error[1024];
    BOOL valid=launcher_options(self.folder.fileSystemRepresentation,
                               [modes[self.mode.indexOfSelectedItem] UTF8String],
                               self.resolution.titleOfSelectedItem.UTF8String,
                               selected,sizeof selected,error,sizeof error);
    self.playButton.enabled=valid;
    self.status.stringValue=valid?@"Official 1.3 and native widescreen support. Each mode has separate saves.":[NSString stringWithUTF8String:error];
}
- (void)changed:(id)sender{(void)sender;[self refresh];}
- (void)play:(id)sender{
    (void)sender;char selected[4096],error[1024];NSArray *modes=@[@"standard",@"visuals",@"full"];
    NSString *mode=modes[self.mode.indexOfSelectedItem];
    if(!launcher_options(self.folder.fileSystemRepresentation,mode.UTF8String,
                         self.resolution.titleOfSelectedItem.UTF8String,selected,sizeof selected,error,sizeof error)){
        self.status.stringValue=[NSString stringWithUTF8String:error];return;
    }
    NSUserDefaults *prefs=NSUserDefaults.standardUserDefaults;
    [prefs setObject:mode forKey:@"GameMode"];
    [prefs setObject:self.resolution.titleOfSelectedItem forKey:@"Resolution"];
    self.selected=[NSString stringWithUTF8String:selected];[NSApp stopModalWithCode:NSModalResponseOK];
}
- (void)cancel:(id)sender{(void)sender;[NSApp stopModalWithCode:NSModalResponseCancel];}
- (BOOL)windowShouldClose:(NSWindow *)sender{(void)sender;[self cancel:nil];return NO;}
@end

static NSTextField *label(NSString *text,NSRect rect,NSView *view){
    NSTextField *field=[NSTextField labelWithString:text];field.frame=rect;[view addSubview:field];return field;
}

NSString *launcher_choose_game(void){
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    NSUserDefaults *prefs=NSUserDefaults.standardUserDefaults;
    /* Older launchers remembered a game folder outside the app; never use it again. */
    [prefs removeObjectForKey:@"GameFolder"];[prefs removeObjectForKey:@"ExternalGameFolder"];
    NSString *folder=launcher_game_folder(NSBundle.mainBundle.resourcePath);
    if(!folder){
        NSAlert *alert=[NSAlert new];alert.alertStyle=NSAlertStyleCritical;
        alert.messageText=@"Most Wanted could not start";alert.informativeText=missing_game;
        [alert addButtonWithTitle:@"Quit"];[NSApp activateIgnoringOtherApps:YES];[alert runModal];
        return nil;
    }
    MWLauncher *controller=[MWLauncher new];controller.folder=folder;
    controller.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,560,284)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
    controller.window.title=@"Most Wanted Launcher";controller.window.releasedWhenClosed=NO;
    controller.window.delegate=controller;NSView *view=controller.window.contentView;
    NSTextField *title=label(@"Need for Speed Most Wanted",NSMakeRect(24,229,500,28),view);
    title.font=[NSFont boldSystemFontOfSize:21];
    label(@"Resolution",NSMakeRect(24,187,105,22),view);
    controller.resolution=[[NSPopUpButton alloc] initWithFrame:NSMakeRect(130,184,405,28) pullsDown:NO];
    NSMutableArray *sizes=[@[@"640x480",@"800x600",@"1024x768",@"1280x720",@"1280x800",@"1280x960",@"1440x900",@"1600x900",@"1680x1050",@"1920x1080",@"1920x1200",@"2560x1440",@"2560x1600",@"3840x2160"] mutableCopy];
    NSScreen *screen=NSScreen.mainScreen;NSSize size=screen.frame.size;CGFloat scale=screen.backingScaleFactor;
    unsigned w=(unsigned)(size.width*scale),h=(unsigned)(size.height*scale);
    if(w>=640&&h>=480&&w<=8192&&h<=8192){NSString *native=[NSString stringWithFormat:@"%ux%u",w,h];if(![sizes containsObject:native])[sizes addObject:native];}
    [controller.resolution addItemsWithTitles:sizes];
    NSString *previous=[prefs stringForKey:@"Resolution"];
    [controller.resolution selectItemWithTitle:[sizes containsObject:previous]?previous:@"1280x720"];
    controller.resolution.target=controller;controller.resolution.action=@selector(changed:);[view addSubview:controller.resolution];
    label(@"Game mode",NSMakeRect(24,141,105,22),view);
    controller.mode=[[NSPopUpButton alloc] initWithFrame:NSMakeRect(130,138,405,28) pullsDown:NO];
    [controller.mode addItemsWithTitles:@[@"Standard",@"HQ visuals only",@"HQ full mod"]];
    NSUInteger index=[@[@"standard",@"visuals",@"full"] indexOfObject:[prefs stringForKey:@"GameMode"]];
    [controller.mode selectItemAtIndex:index==NSNotFound?0:(NSInteger)index];
    controller.mode.target=controller;controller.mode.action=@selector(changed:);[view addSubview:controller.mode];
    controller.status=[NSTextField wrappingLabelWithString:@""];controller.status.frame=NSMakeRect(24,65,510,60);
    controller.status.textColor=NSColor.secondaryLabelColor;[view addSubview:controller.status];
    NSButton *cancel=[NSButton buttonWithTitle:@"Cancel" target:controller action:@selector(cancel:)];
    cancel.frame=NSMakeRect(325,20,100,32);cancel.keyEquivalent=@"\e";[view addSubview:cancel];
    controller.playButton=[NSButton buttonWithTitle:@"Play" target:controller action:@selector(play:)];
    controller.playButton.frame=NSMakeRect(435,20,100,32);controller.playButton.keyEquivalent=@"\r";[view addSubview:controller.playButton];
    [controller refresh];[controller.window center];[controller.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
    [NSApp runModalForWindow:controller.window];[controller.window orderOut:nil];
    return controller.selected;
}
