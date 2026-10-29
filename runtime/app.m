#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <unistd.h>

static BOOL bundled(void){return [[[NSBundle mainBundle].bundlePath pathExtension] isEqualToString:@"app"];}

void app_show_error(const char *text){
    fprintf(stderr,"%s\n",text);
    if(bundled()){
        [NSApplication sharedApplication];NSAlert *alert=[NSAlert new];
        alert.messageText=@"Most Wanted could not start";
        alert.informativeText=[NSString stringWithUTF8String:text];[alert runModal];
    }
}

int app_prepare(const char *argument,char *exe,size_t exe_size,char *save,size_t save_size,char *registry,size_t registry_size){
    @autoreleasepool{
        NSFileManager *files=[NSFileManager defaultManager];
        if(bundled()){
            setenv("WINDOW","1",0);
            setenv("ALARM","0",0);
        }
        NSString *game=argument?[NSString stringWithUTF8String:argument]:nil;
        if(!game&&bundled()){
            [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
            NSOpenPanel *panel=[NSOpenPanel openPanel];panel.canChooseFiles=NO;panel.canChooseDirectories=YES;
            panel.allowsMultipleSelection=NO;panel.message=@"Select the folder containing your Most Wanted game files.";
            panel.prompt=@"Play";
            NSString *previous=[[NSUserDefaults standardUserDefaults] stringForKey:@"GameFolder"];
            if(previous)panel.directoryURL=[NSURL fileURLWithPath:previous isDirectory:YES];
            [NSApp activateIgnoringOtherApps:YES];
            if([panel runModal]!=NSModalResponseOK)return 0;
            NSString *folder=panel.URL.path;
            [[NSUserDefaults standardUserDefaults] setObject:folder forKey:@"GameFolder"];
            game=[folder stringByAppendingPathComponent:@"speed.exe"];
        }
        if(!game)game=@"game/speed.exe";
        if(bundled()&&![game isAbsolutePath])game=[files.currentDirectoryPath stringByAppendingPathComponent:game];
        NSString *state=bundled()?[NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"NFSMW"]:files.currentDirectoryPath;
        const char *custom=getenv("NFSMW_SAVEDIR");
        NSString *saves=custom?[NSString stringWithUTF8String:custom]:[state stringByAppendingPathComponent:bundled()?@"Saves":@"out/profile"];
        if(![saves isAbsolutePath])saves=[files.currentDirectoryPath stringByAppendingPathComponent:saves];
        NSError *error=nil;
        if(![files createDirectoryAtPath:saves withIntermediateDirectories:YES attributes:nil error:&error])return -1;
        if(bundled()){
            if(![files createDirectoryAtPath:state withIntermediateDirectories:YES attributes:nil error:&error])return -1;
            NSString *logs=[NSSearchPathForDirectoriesInDomains(NSLibraryDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"Logs/NFSMW"];
            if(![files createDirectoryAtPath:logs withIntermediateDirectories:YES attributes:nil error:&error])return -1;
            if(!freopen([[logs stringByAppendingPathComponent:@"last-run.log"] fileSystemRepresentation],"w",stderr))return -1;
            setvbuf(stderr,NULL,_IONBF,0);
            if(chdir(state.fileSystemRepresentation))return -1;
        }
        int n=snprintf(exe,exe_size,"%s",game.fileSystemRepresentation);
        int s=snprintf(save,save_size,"%s",saves.fileSystemRepresentation);
        int r=snprintf(registry,registry_size,"%s",[saves stringByAppendingPathComponent:@"registry"].fileSystemRepresentation);
        return n>=0&&(size_t)n<exe_size&&s>=0&&(size_t)s<save_size&&r>=0&&(size_t)r<registry_size?1:-1;
    }
}
