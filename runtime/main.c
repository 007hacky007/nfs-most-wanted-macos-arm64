#include "cpu.h"
#include "target.h"
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
    puts("Kernel timer: relative deadline, auto-reset and timeout passed");
}

static void report(void){
    dispatch_report(); win32_report(); com_report();
}

static void timed_out(int sig){
    (void)sig;
    fprintf(stderr,"Most Wanted time limit; esp=%08x eip=%08x\n",cpu.esp,cpu.eip);
    guest_backtrace(&cpu,24); report(); _exit(124);
}

static int check_exe(const char *path){
    FILE *f = fopen(path,"rb");
    if (!f) { perror("speed.exe"); return 0; }
    CC_SHA256_CTX ctx; CC_SHA256_Init(&ctx);
    unsigned char data[65536], digest[32]; size_t n;
    while ((n=fread(data,1,sizeof data,f))) CC_SHA256_Update(&ctx,data,(CC_LONG)n);
    int ok=!ferror(f); fclose(f); CC_SHA256_Final(digest,&ctx);
    char hex[65]; for (int i=0;i<32;i++) snprintf(hex+2*i,3,"%02x",digest[i]);
    return ok && !strcmp(hex,MW_EXE_SHA);
}

static void *run_game(void *unused){
    (void)unused;
    CPU *c=&cpu;
    mem_altstack_install();
    if (!setjmp(g_exit_jmp)){
        g_exit_armed=1;
        guest_lock(c);
        if(kernel_probe){ test_kernel(c);g_exit_armed=0;guest_unlock();return NULL; }
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
    kernel_probe=argc>1&&!strcmp(argv[1],"--test-kernel");
    char exe[4096],saves[4096],registry[4096];
    int app_prepare(const char *,char *,size_t,char *,size_t,char *,size_t);
    void app_show_error(const char *);
    int paths=app_prepare(argc>1&&!kernel_probe?argv[1]:NULL,exe,sizeof exe,saves,sizeof saves,registry,sizeof registry);
    if(paths==0)return 0;
    if(paths<0){app_show_error("Cannot create the save or log directory.");return 2;}
    int automation_load(const char *);
    if(!automation_load(getenv("NFSMW_INPUT_SCRIPT"))){fprintf(stderr,"Invalid input script\n");return 2;}
    int automation_open_commands(const char *);
    if(!automation_open_commands(getenv("NFSMW_COMMANDS"))){fprintf(stderr,"Cannot open command file\n");return 2;}
    if (!check_exe(exe)){app_show_error("Unsupported speed.exe. Select the installed PC v1.3 game folder used for this build.");return 2;}
    mkdir("out",0755);
    setenv("NFSU2_REGFILE",registry,1);
    setenv("NFSU2_SAVEDIR",saves,1);
    setenv("NFSU2_NET","off",1); setenv("NFSU2_ONLINE","0",1);
    mem_init(); mem_fault_handler_install();
    if (mem_load_pe(exe)) return 2;
    const uint32_t teb=0x00c00000u, peb=0x00c10000u, lo=0x7f000000u, hi=0x7ff00000u;
    mem_commit(teb,0x20000); mem_commit(lo,hi-lo);
    MR32(teb)=0xffffffffu; MR32(teb+4)=hi; MR32(teb+8)=lo;
    MR32(teb+0x18)=teb; MR32(teb+0x20)=100; MR32(teb+0x24)=1;
    MR32(teb+0x2c)=teb+0x1000; MR32(teb+0x30)=peb;
    MR32(peb+8)=MW_BASE; MR32(peb+0xa4)=5; MR32(peb+0xa8)=1;
    cpu.esp=hi-0x1000; cpu.fcw=0x027f; cpu.fs_base=teb; cpu.gs_base=teb;
    extern CPU *g_cur_cpu; g_cur_cpu=&cpu;
    fileio_set_root(exe); fileio_set_write_root(saves); fileio_set_readonly_root(1);
    dispatch_init(); win32_init();
    signal(SIGALRM,timed_out);
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
