#include "cpu.h"
#include "target.h"
#include "module.h"
#if NFS_HQ_MODULES
#include "hq_plugin.h"
#include "hq_image.h"
#include "hq_capture.h"
#include "hq_prepare.h"
#endif
#include "widescreen.h"
#include <CommonCrypto/CommonDigest.h>
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include <assert.h>

extern _Thread_local jmp_buf g_exit_jmp;
extern _Thread_local int g_exit_armed;
extern int g_exit_code;
void mem_init(void), mem_commit(uint32_t,uint32_t), mem_fault_handler_install(void), mem_altstack_install(void);
int mem_load_pe(const char *);
void dispatch_init(void), dispatch_report(void), win32_init(void), win32_report(void), com_report(void);
void guest_lock(CPU *), guest_unlock(void), guest_backtrace(CPU *,int);
void fileio_set_root(const char *), fileio_set_write_root(const char *), fileio_set_readonly_root(int);
void lifecycle_guest_exited(int), metal_early_init(void), metal_run_main_loop(void);
static CPU cpu;
static int kernel_probe;
static int module_prepare;
static int enum_keyboards;
static void enum_probe(CPU *c){
    POP32(c->eip);uint32_t instance=MR32(c->esp);
    if(MR32(instance+4)==0x6f1d2b61u)enum_keyboards++;
    c->eax=1;c->esp+=8;
}

static void test_kernel(CPU *c){
    int win32_ext_call(CPU *,const char *,uint32_t *);
    uint32_t result=0;
    MR32(c->esp)=0;MR32(c->esp+4)=0;MR32(c->esp+8)=0;
    assert(win32_ext_call(c,"CreateWaitableTimerA",&result)&&result);
    uint32_t handle=result,due=c->esp+64;
    MR64(due)=(uint64_t)(int64_t)-100000;
    MR32(c->esp)=handle;MR32(c->esp+4)=due;
    MR32(c->esp+8)=0;MR32(c->esp+12)=0;MR32(c->esp+16)=0;MR32(c->esp+20)=0;
    assert(win32_ext_call(c,"SetWaitableTimer",&result)&&result);
    MR32(c->esp+4)=0;
    assert(win32_ext_call(c,"WaitForSingleObject",&result)&&result==0x102);
    MR32(c->esp+4)=200;
    assert(win32_ext_call(c,"WaitForSingleObject",&result)&&result==0);
    MR32(c->esp+4)=0;
    assert(win32_ext_call(c,"WaitForSingleObject",&result)&&result==0x102);
    assert(win32_ext_call(c,"CloseHandle",&result));
    uint32_t memory=c->esp+2048;
    memset(g_mem+memory,0xa5,72);MR32(memory)=64;MR32(c->esp)=memory;
    assert(win32_ext_call(c,"GlobalMemoryStatusEx",&result)&&result);
    assert(MR32(memory)==64&&MR32(memory+4)<=100);
    assert(MR64(memory+8)>0&&MR64(memory+16)<=MR64(memory+8));
    assert(MR64(memory+24)>0&&MR64(memory+32)<=MR64(memory+24));
    assert(MR64(memory+40)==0x80000000ull&&MR64(memory+48)<=MR64(memory+40));
    assert(MR64(memory+56)==0&&MR64(memory+64)==0xa5a5a5a5a5a5a5a5ull);
    MR32(memory)=63;
    assert(win32_ext_call(c,"GlobalMemoryStatusEx",&result)&&!result);
    assert(MR32(memory)==63);
    MR32(c->esp)=0;assert(win32_ext_call(c,"GlobalMemoryStatusEx",&result)&&!result);
    uint32_t system=c->esp+96,file=c->esp+128;
    memset(g_mem+system,0,16);MR16(system)=1970;MR16(system+2)=1;MR16(system+6)=1;
    MR32(c->esp)=system;MR32(c->esp+4)=file;
    assert(win32_ext_call(c,"SystemTimeToFileTime",&result)&&result);
    assert(MR64(file)==116444736000000000ull);
    MR16(system)=2025;MR16(system+2)=2;MR16(system+6)=29;
    assert(win32_ext_call(c,"SystemTimeToFileTime",&result)&&!result);
    uint32_t input=c->esp+160;memset(g_mem+input,0,28);
    MR32(input+4)=2;MR32(input+8)=3;MR32(input+16)=1;
    MR32(c->esp)=1;MR32(c->esp+4)=input;MR32(c->esp+8)=28;
    assert(win32_ext_call(c,"SendInput",&result)&&result==1);
    void metal_fill_mouse(unsigned char *,unsigned);
    unsigned char mouse[20];metal_fill_mouse(mouse,sizeof mouse);
    int dx,dy;memcpy(&dx,mouse,4);memcpy(&dy,mouse+4,4);assert(dx==2&&dy==3);
    uint32_t com_directinput8create(uint32_t),call_guest(CPU *,uint32_t,int,const uint32_t *);
    void dispatch_patch(uint32_t,void (*)(CPU *));
    uint32_t out=c->esp+256;assert(!com_directinput8create(out));uint32_t di=MR32(out);
    dispatch_patch(0x00b80000u,enum_probe);
    uint32_t args[]={di,3,0x00b80000u,0,0};
    assert(!call_guest(c,MR32(MR32(di)+16),5,args));assert(enum_keyboards==1);
    uint32_t original=MR32(0x8364e8u);args[1]=4;
    assert(!call_guest(c,MR32(MR32(di)+16),5,args));assert(MR32(0x8364e8u)==original);
    uint32_t com_devinst(int);
    uint32_t create[]={di,com_devinst(1)+4,out+4,0};
    assert(!call_guest(c,MR32(MR32(di)+12),4,create));uint32_t keyboard=MR32(out+4);
    uint32_t format[]={keyboard,0x008c8194u};
    assert(!call_guest(c,MR32(MR32(keyboard)+44),2,format));
    uint32_t acquire[]={keyboard};assert(!call_guest(c,MR32(MR32(keyboard)+28),1,acquire));
    void kbd_set_key(int,unsigned,int);
    kbd_set_key(1,0xcb,1);
    uint32_t readstate[]={keyboard,256,out+512};
    assert(!call_guest(c,MR32(MR32(keyboard)+36),3,readstate));assert(MR8(out+512+0xcb)==0x80);
    kbd_set_key(1,0xcb,0);
    puts("Kernel timers, memory status and input checks passed");
}

static void report(void){
    dispatch_report(); win32_report(); com_report();
    void mw_texwizard_report(void);mw_texwizard_report();
}

static void timed_out(int sig){
    (void)sig;
    fprintf(stderr,"Most Wanted time limit; esp=%08x eip=%08x\n",cpu.esp,cpu.eip);
    guest_backtrace(&cpu,24); report(); _exit(124);
}

int hq_image_hash(const char *path,const char *expected){
    FILE *f = fopen(path,"rb");
    if (!f) { perror("speed.exe"); return 0; }
    CC_SHA256_CTX ctx; CC_SHA256_Init(&ctx);
    unsigned char data[65536], digest[32]; size_t n;
    while ((n=fread(data,1,sizeof data,f))) CC_SHA256_Update(&ctx,data,(CC_LONG)n);
    int ok=!ferror(f); fclose(f); CC_SHA256_Final(digest,&ctx);
    char hex[65]; for (int i=0;i<32;i++) snprintf(hex+2*i,3,"%02x",digest[i]);
    return ok && !strcmp(hex,expected);
}

#define BASE_IMAGE_SHA "80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c"
#define OFFICIAL_IMAGE_SHA "e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb"
static int native_image(const char *path){return hq_image_hash(path,BASE_IMAGE_SHA);}

static void *run_game(void *unused){
    (void)unused;
    CPU *c=&cpu;
    mem_altstack_install();
    if (!setjmp(g_exit_jmp)){
        g_exit_armed=1;
        guest_lock(c);
        if(kernel_probe){ test_kernel(c);g_exit_armed=0;guest_unlock();return NULL; }
#if NFS_HQ_MODULES
        { const char *mode=getenv("NFSMW_MODE");
          if(mode&&!strcmp(mode,"full")&&!hq_plugin_prepare(c,NULL)){
              g_exit_code=2;g_exit_armed=0;guest_unlock();lifecycle_guest_exited(2);return NULL;
          } }
        if(module_prepare){
            if(module_prepare==2&&!hq_prepare_run(c)){
                g_exit_code=2;g_exit_armed=0;guest_unlock();lifecycle_guest_exited(2);return NULL;
            }
            hq_capture(c,"modules",0);
            fprintf(stderr,"HQ module preparation finished before game entry\n");
            g_exit_armed=0;guest_unlock();lifecycle_guest_exited(0);return NULL;
        }
#endif
        PUSH32(0xdeadc0deu);
        fprintf(stderr,"Executing Most Wanted entry %08x as native ARM64\n",MW_ENTRY);
        dispatch_indirect(c,MW_ENTRY);
        guest_unlock();
        fprintf(stderr,"Guest entry returned: eax=%08x eip=%08x\n",c->eax,c->eip);
    } else {
        fprintf(stderr,"Guest exited with code %d\n",g_exit_code);
        guest_unlock();
    }
    g_exit_armed=0;
    lifecycle_guest_exited(g_exit_code);
    return NULL;
}

int main(int argc,char **argv){
    module_prepare=argc>1&&!strcmp(argv[1],"--prepare-hq-modules");
    if(argc>1&&!strcmp(argv[1],"--prepare-hq-runtime"))module_prepare=2;
    if(module_prepare){
#if NFS_HQ_MODULES
        const char *captures=getenv("NFSMW_HQ_CAPTURE_DIR");struct stat info;
        if(argc!=3||!captures||stat(captures,&info)||!S_ISDIR(info.st_mode)||access(captures,W_OK|X_OK)){
            fprintf(stderr,"Usage: NFSMW_HQ_CAPTURE_DIR=existing-folder %s --prepare-hq-modules game/speed.exe\n",argv[0]);return 2;
        }
        setenv("NFSMW_MODE","full",1);
#else
        fprintf(stderr,"HQ module preparation requires a build with --hq\n");return 2;
#endif
    }
    kernel_probe=argc>1&&!strcmp(argv[1],"--test-kernel");
    char exe[4096],image[4096],saves[4096],registry[4096];
    int app_prepare(const char *,char *,size_t,char *,size_t,char *,size_t);
    void app_show_error(const char *);
    int paths=app_prepare(module_prepare?argv[2]:argc>1&&!kernel_probe?argv[1]:NULL,exe,sizeof exe,saves,sizeof saves,registry,sizeof registry);
    if(paths==0)return 0;
    if(paths<0){app_show_error(paths==-2?"Cannot start the game engine. Rebuild the app and try again.":
                             "Cannot create the save or log directory.");return 2;}
    { const char *mode=getenv("NFSMW_MODE");int app_full_hq_supported(void);
      int experimental=0;
#if NFS_HQ_MODULES
      const char *setting=getenv("NFSMW_EXPERIMENTAL_FULL");experimental=setting&&!strcmp(setting,"1");
#endif
      if(mode&&!strcmp(mode,"full")&&!app_full_hq_supported()&&!experimental&&!module_prepare){
          app_show_error("HQ full mod is unavailable in this build. Its native renderer and code mods are still being ported.");return 2;
      } }
    int automation_load(const char *);
    if(!automation_load(getenv("NFSMW_INPUT_SCRIPT"))){fprintf(stderr,"Invalid input script\n");return 2;}
    int automation_open_commands(const char *);
    if(!automation_open_commands(getenv("NFSMW_COMMANDS"))){fprintf(stderr,"Cannot open command file\n");return 2;}
#if NFS_HQ_MODULES
    {const char *mode=getenv("NFSMW_MODE");
     if(!hq_image_select(exe,image,sizeof image,mode&&!strcmp(mode,"full"))){
         app_show_error("Unsupported game data or missing verified runtime image.");return 2;
     }}
#else
    snprintf(image,sizeof image,"%s",exe);
    if(!native_image(exe)){
        int app_runtime_image(const char *,char *,size_t);
        if(!hq_image_hash(exe,OFFICIAL_IMAGE_SHA)||!app_runtime_image(exe,image,sizeof image)||!native_image(image)){
            app_show_error("Unsupported game image. Install the supplied ISO discs and patches, then select that installation.");return 2;
        }
        fprintf(stderr,"Using the verified native runtime image with official 1.3 game files\n");
    }
#endif
    mkdir("out",0755);
    setenv("NFSU2_REGFILE",registry,1);
    setenv("NFSU2_SAVEDIR",saves,1);
    setenv("NFSU2_NET","off",1); setenv("NFSU2_ONLINE","0",1);
    mem_init(); mem_fault_handler_install();
    if (mem_load_pe(image)) return 2;
    const uint32_t teb=0x00c00000u, peb=0x00c10000u, lo=0x7f000000u, hi=0x7ff00000u;
    mem_commit(teb,0x20000); mem_commit(lo,hi-lo);
    MR32(teb)=0xffffffffu; MR32(teb+4)=hi; MR32(teb+8)=lo;
    MR32(teb+0x18)=teb; MR32(teb+0x20)=100; MR32(teb+0x24)=1;
    MR32(teb+0x2c)=teb+0x1000; MR32(teb+0x30)=peb;
    MR32(peb+8)=MW_BASE; MR32(peb+0xa4)=5; MR32(peb+0xa8)=1;
    cpu.esp=hi-0x1000; cpu.fcw=0x027f; cpu.fs_base=teb; cpu.gs_base=teb;
    extern CPU *g_cur_cpu; g_cur_cpu=&cpu;
    fileio_set_root(exe); fileio_set_write_root(saves); fileio_set_readonly_root(1);
    { char directory[4096];snprintf(directory,sizeof directory,"%s",exe);
      char *slash=strrchr(directory,'/');if(slash)*slash=0;else strcpy(directory,".");
      void ws_configure(const char *);ws_configure(directory); }
    dispatch_init(); win32_init();
#if NFS_HQ_MODULES
    {void hq_game_register(void);hq_game_register();}
#endif
    if(!ws_patch_init()){
        app_show_error("Widescreen patch settings are invalid or unsupported.");return 2;
    }
    { void mw_unlimiter_init(int);const char *mode=getenv("NFSMW_MODE");
#if NFS_HQ_MODULES
      hq_plugin_init_unlimiter(mode&&!strcmp(mode,"full"));
#else
      mw_unlimiter_init(mode&&!strcmp(mode,"full"));
#endif
      void mw_hdscaling_init(int);mw_hdscaling_init(mode&&!strcmp(mode,"full"));
      int mw_motionblur_init(int);
      if(!mw_motionblur_init(mode&&!strcmp(mode,"full"))){
          app_show_error("HQ motion blur settings are invalid.");return 2;
      }
      int mw_fixes_init(int);
      if(!mw_fixes_init(mode&&!strcmp(mode,"full"))){
          app_show_error("HQ stability patch settings are invalid or unsupported.");return 2;
      }
      int mw_fe_shadows_init(int),mw_hud_adapter_init(int);
      if(!mw_fe_shadows_init(mode&&!strcmp(mode,"full"))){
          app_show_error("HQ frontend shadow settings are invalid or unsupported.");return 2;
      }
      if(!mw_hud_adapter_init(mode&&!strcmp(mode,"full"))){
          app_show_error("HQ HUD initialization failed.");return 2;
      }
      int mw_hdreflections_init(int);
      if(!mw_hdreflections_init(mode&&!strcmp(mode,"full"))){
          app_show_error("HQ reflection settings are invalid or unsupported.");return 2;
      }
      void mw_hdcontent_init(int);mw_hdcontent_init(mode&&(!strcmp(mode,"visuals")||!strcmp(mode,"full")));
      int mw_texwizard_init(int);
      if(!mw_texwizard_init(mode&&(!strcmp(mode,"visuals")||!strcmp(mode,"full")))){
          app_show_error("HQ texture data is missing or invalid. Reinstall the HQ assets.");return 2;
      } }
    signal(SIGALRM,timed_out);
    if(module_prepare)unsetenv("WINDOW");
    alarm(getenv("ALARM")?(unsigned)atoi(getenv("ALARM")):30);
    if (getenv("WINDOW")){
        int metal_available(void);
        metal_early_init();
        if(!metal_available()){fprintf(stderr,"Metal is unavailable; cannot run the game window\n");return 3;}
    }
    pthread_attr_t attr; pthread_attr_init(&attr); pthread_attr_setstacksize(&attr,256*1024*1024);
    pthread_t guest; int error=pthread_create(&guest,&attr,run_game,NULL); pthread_attr_destroy(&attr);
    if (error){ fprintf(stderr,"Cannot start guest thread: %d\n",error); return 2; }
    if (getenv("WINDOW")) metal_run_main_loop();
    else if(kernel_probe)pthread_join(guest,NULL);
    else {
        int lifecycle_guest_has_exited(void);
        while(!lifecycle_guest_has_exited())usleep(1000);
    }
    int lifecycle_drain_writes(double),win32_freeze_guest(int);
    lifecycle_drain_writes(5.0);
    if(!win32_freeze_guest(2000))fprintf(stderr,"A guest thread did not stop before shutdown\n");
    alarm(0); report();
    return g_exit_code;
}
