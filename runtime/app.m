#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <unistd.h>
NSString *launcher_choose_game(void);

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
            NSString *folder=launcher_choose_game();
            if(!folder)return 0;
            game=[folder stringByAppendingPathComponent:@"speed.exe"];
        }
        if(!game)game=@"game/speed.exe";
        if(bundled()&&![game isAbsolutePath])game=[files.currentDirectoryPath stringByAppendingPathComponent:game];
        NSString *state=bundled()?[NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory,NSUserDomainMask,YES).firstObject stringByAppendingPathComponent:@"NFSMW"]:files.currentDirectoryPath;
        const char *custom=getenv("NFSMW_SAVEDIR");
        NSString *saves=custom?[NSString stringWithUTF8String:custom]:[state stringByAppendingPathComponent:bundled()?@"Saves":@"out/profile"];
        const char *mode=getenv("NFSMW_MODE");
        if(!custom&&mode&&(!strcmp(mode,"visuals")||!strcmp(mode,"full")))
            saves=[saves stringByAppendingPathComponent:!strcmp(mode,"visuals")?@"HQVisuals":@"HQFull"];
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

int app_runtime_image(const char *game,char *image,size_t image_size){
    @autoreleasepool{
        NSString *folder=[[NSString stringWithUTF8String:game] stringByDeletingLastPathComponent];
        NSString *candidate=[folder stringByAppendingPathComponent:@".nfsmw/runtime.exe"];
        if(![NSFileManager.defaultManager fileExistsAtPath:candidate])
            candidate=[NSBundle.mainBundle pathForResource:@"runtime-image" ofType:@"exe"];
        if(!candidate)return 0;
        int n=snprintf(image,image_size,"%s",candidate.fileSystemRepresentation);
        return n>=0&&(size_t)n<image_size;
    }
}
