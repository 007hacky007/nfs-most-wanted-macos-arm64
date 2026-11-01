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

/* --- update check ---------------------------------------------------------
 * New features arrive only with a new NFSMW Builder release. NFSMW Builder stamps its
 * version into the app (NFSBuilderVersion, tools/package_app.py); at most once a day,
 * when "Check for updates" is on, the launcher asks GitHub for the latest release and
 * offers it. It never downloads or runs anything itself: the buttons open the release
 * page or the disk image in the default browser. */
static NSString *const update_repository=@"007hacky007/nfs-most-wanted-macos-arm64";
static NSString *const update_asset=@"NFSMW-Builder.dmg";
static NSString *const check_key=@"CheckForUpdates",*const last_check_key=@"LastUpdateCheck",
                *const dismissed_key=@"DismissedUpdateVersion";

/* Numeric per dot-separated component; text after the digits ("0.4.0-dev") is ignored. */
int launcher_compare_versions(NSString *a,NSString *b){
    NSArray *left=[a componentsSeparatedByString:@"."],*right=[b componentsSeparatedByString:@"."];
    for(NSUInteger i=0;i<MAX(left.count,right.count);i++){
        long long x=i<left.count?[left[i] longLongValue]:0,y=i<right.count?[right[i] longLongValue]:0;
        if(x!=y)return x<y?-1:1;
    }
    return 0;
}

NSString *launcher_builder_version(void){
    id version=NSBundle.mainBundle.infoDictionary[@"NFSBuilderVersion"];
    return [version isKindOfClass:NSString.class]&&[version length]?version:nil;
}

BOOL launcher_update_checks_enabled(NSUserDefaults *prefs){
    id value=[prefs objectForKey:check_key];
    return value?[value boolValue]:YES;
}

/* At most once per 24 hours; a clock set back makes the next check due. */
BOOL launcher_update_due(NSUserDefaults *prefs,NSDate *now){
    id last=[prefs objectForKey:last_check_key];
    if(![last isKindOfClass:NSDate.class])return YES;
    NSTimeInterval since=[now timeIntervalSinceDate:last];
    return since<0||since>=24*60*60;
}

NSURLRequest *launcher_update_request(void){
    NSString *url=[NSString stringWithFormat:@"https://api.github.com/repos/%@/releases/latest",update_repository];
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:url]
        cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:5];
    request.HTTPShouldHandleCookies=NO;
    /* Set so the system does not add the Mac's own language list. */
    [request setValue:@"NFSMW-Launcher" forHTTPHeaderField:@"User-Agent"];
    [request setValue:@"application/vnd.github+json" forHTTPHeaderField:@"Accept"];
    [request setValue:@"en" forHTTPHeaderField:@"Accept-Language"];
    return request;
}

static BOOL github_url(id value){
    NSURL *url=[value isKindOfClass:NSString.class]?[NSURL URLWithString:value]:nil;
    return [url.scheme isEqualToString:@"https"]&&[url.host isEqualToString:@"github.com"];
}

/* The release to offer, {version, notes, download}, or nil when it is not newer than the
 * app's Builder or than a version dismissed with Not now. */
NSDictionary *launcher_update_offer(NSData *json,NSString *stamp,NSString *dismissed){
    NSDictionary *release=json?[NSJSONSerialization JSONObjectWithData:json options:0 error:nil]:nil;
    if(![release isKindOfClass:NSDictionary.class]||!stamp.length)return nil;
    NSString *tag=release[@"tag_name"];
    if(![tag isKindOfClass:NSString.class]||!tag.length)return nil;
    NSString *version=[tag hasPrefix:@"v"]?[tag substringFromIndex:1]:tag;
    NSCharacterSet *allowed=[NSCharacterSet characterSetWithCharactersInString:@"0123456789.-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"];
    if(!version.length||version.length>32||[version rangeOfCharacterFromSet:allowed.invertedSet].location!=NSNotFound
       ||[version characterAtIndex:0]<'0'||[version characterAtIndex:0]>'9')return nil;
    if(launcher_compare_versions(version,stamp)<=0)return nil;
    if(dismissed.length&&launcher_compare_versions(version,dismissed)<=0)return nil;
    NSString *download=nil;
    NSArray *assets=release[@"assets"];
    if([assets isKindOfClass:NSArray.class])
        for(NSDictionary *asset in assets)
            if([asset isKindOfClass:NSDictionary.class]&&[asset[@"name"] isEqual:update_asset]&&github_url(asset[@"browser_download_url"]))
                download=asset[@"browser_download_url"];
    if(!download||!github_url(release[@"html_url"]))return nil;
    return @{@"version":version,@"notes":release[@"html_url"],@"download":download};
}

typedef void (^LauncherFetch)(NSURLRequest *request,void (^done)(NSData *body));
/* Tests replace this; nil uses an ephemeral URL session (no cookies, cache or credentials). */
LauncherFetch launcher_update_fetch=nil;

static void fetch_release(NSURLRequest *request,void (^done)(NSData *)){
    if(launcher_update_fetch){launcher_update_fetch(request,done);return;}
    NSURLSessionConfiguration *configuration=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.timeoutIntervalForRequest=5;configuration.timeoutIntervalForResource=5;
    configuration.HTTPShouldSetCookies=NO;configuration.HTTPCookieStorage=nil;
    configuration.URLCache=nil;configuration.URLCredentialStorage=nil;
    NSURLSession *session=[NSURLSession sessionWithConfiguration:configuration];
    [[session dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
        NSHTTPURLResponse *http=(NSHTTPURLResponse *)response;
        done(!error&&[http isKindOfClass:NSHTTPURLResponse.class]&&http.statusCode==200?data:nil);
    }] resume];
    [session finishTasksAndInvalidate];
}

/* Starts the background check when it is on, the app has a Builder stamp and a day has
 * passed. `offer` runs on the main queue, only for a newer release; failures stay silent. */
BOOL launcher_check_for_updates(NSUserDefaults *prefs,NSString *stamp,NSDate *now,void (^offer)(NSDictionary *)){
    if(!stamp.length||!launcher_update_checks_enabled(prefs)||!launcher_update_due(prefs,now))return NO;
    [prefs setObject:now forKey:last_check_key];
    NSString *dismissed=[prefs stringForKey:dismissed_key];
    fetch_release(launcher_update_request(),^(NSData *body){
        NSDictionary *found=launcher_update_offer(body,stamp,dismissed);
        if(found)dispatch_async(dispatch_get_main_queue(),^{offer(found);});
    });
    return YES;
}

@interface MWLauncher : NSObject <NSWindowDelegate>
@property NSWindow *window;
@property NSTextField *status,*updateText;
@property NSPopUpButton *resolution,*mode;
@property NSButton *playButton,*updatesBox;
@property NSView *updateNotice;
@property NSString *folder,*selected,*stamp;
@property NSDictionary *offer;
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
- (void)checkForUpdates{
    __weak MWLauncher *weak=self;
    launcher_check_for_updates(NSUserDefaults.standardUserDefaults,self.stamp,[NSDate date],^(NSDictionary *found){
        MWLauncher *strong=weak;if(!strong)return;
        strong.offer=found;
        strong.updateText.stringValue=[NSString stringWithFormat:@"NFSMW Builder %@ is available",found[@"version"]];
        strong.updateNotice.hidden=NO;
    });
}
- (void)toggleUpdates:(id)sender{
    (void)sender;BOOL on=self.updatesBox.state==NSControlStateValueOn;
    [NSUserDefaults.standardUserDefaults setObject:@(on) forKey:check_key];
    if(on)[self checkForUpdates];
}
- (void)whatsNew:(id)sender{(void)sender;if(self.offer)[NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:self.offer[@"notes"]]];}
/* The browser downloads the disk image like any other, quarantined; the launcher never does. */
- (void)download:(id)sender{(void)sender;if(self.offer)[NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:self.offer[@"download"]]];}
- (void)notNow:(id)sender{
    (void)sender;
    if(self.offer)[NSUserDefaults.standardUserDefaults setObject:self.offer[@"version"] forKey:dismissed_key];
    self.updateNotice.hidden=YES;
}
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
    MWLauncher *controller=[MWLauncher new];controller.folder=folder;controller.stamp=launcher_builder_version();
    controller.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,560,384)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
    controller.window.title=@"Most Wanted Launcher";controller.window.releasedWhenClosed=NO;
    controller.window.delegate=controller;NSView *view=controller.window.contentView;
    NSTextField *title=label(@"Need for Speed Most Wanted",NSMakeRect(24,329,500,28),view);
    title.font=[NSFont boldSystemFontOfSize:21];
    label(@"Resolution",NSMakeRect(24,287,105,22),view);
    controller.resolution=[[NSPopUpButton alloc] initWithFrame:NSMakeRect(130,284,405,28) pullsDown:NO];
    NSMutableArray *sizes=[@[@"640x480",@"800x600",@"1024x768",@"1280x720",@"1280x800",@"1280x960",@"1440x900",@"1600x900",@"1680x1050",@"1920x1080",@"1920x1200",@"2560x1440",@"2560x1600",@"3840x2160"] mutableCopy];
    NSScreen *screen=NSScreen.mainScreen;NSSize size=screen.frame.size;CGFloat scale=screen.backingScaleFactor;
    unsigned w=(unsigned)(size.width*scale),h=(unsigned)(size.height*scale);
    if(w>=640&&h>=480&&w<=8192&&h<=8192){NSString *native=[NSString stringWithFormat:@"%ux%u",w,h];if(![sizes containsObject:native])[sizes addObject:native];}
    [controller.resolution addItemsWithTitles:sizes];
    NSString *previous=[prefs stringForKey:@"Resolution"];
    [controller.resolution selectItemWithTitle:[sizes containsObject:previous]?previous:@"1280x720"];
    controller.resolution.target=controller;controller.resolution.action=@selector(changed:);[view addSubview:controller.resolution];
    label(@"Game mode",NSMakeRect(24,241,105,22),view);
    controller.mode=[[NSPopUpButton alloc] initWithFrame:NSMakeRect(130,238,405,28) pullsDown:NO];
    [controller.mode addItemsWithTitles:@[@"Standard",@"HQ visuals only",@"HQ full mod"]];
    NSUInteger index=[@[@"standard",@"visuals",@"full"] indexOfObject:[prefs stringForKey:@"GameMode"]];
    [controller.mode selectItemAtIndex:index==NSNotFound?0:(NSInteger)index];
    controller.mode.target=controller;controller.mode.action=@selector(changed:);[view addSubview:controller.mode];
    label(@"Updates",NSMakeRect(24,195,105,22),view);
    controller.updatesBox=[NSButton checkboxWithTitle:@"Check for updates" target:controller action:@selector(toggleUpdates:)];
    controller.updatesBox.frame=NSMakeRect(131,195,405,22);[view addSubview:controller.updatesBox];
    controller.updatesBox.state=controller.stamp&&launcher_update_checks_enabled(prefs)?NSControlStateValueOn:NSControlStateValueOff;
    controller.updatesBox.enabled=controller.stamp!=nil;
    NSTextField *about=[NSTextField wrappingLabelWithString:controller.stamp
        ?@"Once a day the launcher asks GitHub whether a newer NFSMW Builder is out. Off: no network request."
        :@"This app was not built with NFSMW Builder, so there is nothing to check. Build it again to update."];
    about.frame=NSMakeRect(133,152,400,38);about.font=[NSFont systemFontOfSize:NSFont.smallSystemFontSize];
    about.textColor=NSColor.secondaryLabelColor;[view addSubview:about];
    controller.status=[NSTextField wrappingLabelWithString:@""];controller.status.frame=NSMakeRect(24,102,510,40);
    controller.status.textColor=NSColor.secondaryLabelColor;[view addSubview:controller.status];
    controller.updateNotice=[[NSView alloc] initWithFrame:NSMakeRect(24,62,512,30)];controller.updateNotice.hidden=YES;
    controller.updateText=label(@"",NSMakeRect(0,5,245,20),controller.updateNotice);
    controller.updateText.font=[NSFont boldSystemFontOfSize:NSFont.systemFontSize];
    NSArray *actions=@[@[@"What's new",NSStringFromSelector(@selector(whatsNew:)),@95],
                       @[@"Download",NSStringFromSelector(@selector(download:)),@90],
                       @[@"Not now",NSStringFromSelector(@selector(notNow:)),@80]];
    CGFloat x=512;
    for(NSArray *action in actions.reverseObjectEnumerator){
        CGFloat width=[action[2] doubleValue];x-=width;
        NSButton *button=[NSButton buttonWithTitle:action[0] target:controller action:NSSelectorFromString(action[1])];
        button.frame=NSMakeRect(x,0,width,30);[controller.updateNotice addSubview:button];x-=6;
    }
    [view addSubview:controller.updateNotice];
    NSButton *cancel=[NSButton buttonWithTitle:@"Cancel" target:controller action:@selector(cancel:)];
    cancel.frame=NSMakeRect(325,20,100,32);cancel.keyEquivalent=@"\e";[view addSubview:cancel];
    controller.playButton=[NSButton buttonWithTitle:@"Play" target:controller action:@selector(play:)];
    controller.playButton.frame=NSMakeRect(435,20,100,32);controller.playButton.keyEquivalent=@"\r";[view addSubview:controller.playButton];
    [controller refresh];[controller.window center];[controller.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
    [controller checkForUpdates];
    [NSApp runModalForWindow:controller.window];[controller.window orderOut:nil];
    return controller.selected;
}
