/* Supplied MWFixes (5ae5d310...) and ZPatchMW (9ebb3689...) behaviors.
 * MWFixes patch bytes match GrimMaple/mwfixes src/dllmain.cpp. ZPatch's
 * two replacement routines were verified from the supplied binary.
 */
#include "cpu.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <time.h>
#define HOOK_SITE(a) a
#define HOOK_BRANCH(a,b) a

int fileio_resolve_game(const char *,char *,size_t);
uint64_t host_qpc(void);
void guest_wait_begin(void),guest_wait_end(void);
enum {STABILITY,PURECALL,TIMEBUG,HANDLER,AICOP,STUTTER,BORDERLESS,OPTIONS};
static int options[OPTIONS],clock_ready;
static uint64_t previous;
static _Thread_local struct {CPU *cpu;uint32_t stack;int top;} timing;

static int read_options(const char *filename,int *values,int first,int last){
    static const char *keys[]={"StabilityFixes","PreventPurecall","TimebugFix",
        "AddPurecallHandler","AICopCarCrashFix","StutterFix","BorderlessFixes"};
    char path[4096],line[512],section[64]="";
    if(!fileio_resolve_game(filename,path,sizeof path))return 0;
    FILE *file=fopen(path,"r");if(!file)return errno==ENOENT;
    int valid=1;
    while(fgets(line,sizeof line,file)){
        if(!strchr(line,'\n')&&!feof(file)){valid=0;break;}
        char *comment=strstr(line,"//");if(comment)*comment=0;
        comment=strchr(line,';');if(comment)*comment=0;
        char *p=line;while(isspace((unsigned char)*p))p++;
        if(*p=='['){section[0]=0;sscanf(p,"[%63[^]]]",section);continue;}
        if(strcasecmp(section,"Fixes"))continue;
        char *value=strchr(p,'=');if(!value)continue;*value++=0;
        size_t length=strlen(p);while(length&&isspace((unsigned char)p[length-1]))p[--length]=0;
        int option=first;while(option<last&&strcasecmp(p,keys[option]))option++;
        if(option==last)continue;
        errno=0;char *end;long parsed=strtol(value,&end,10);int number=end!=value;
        while(isspace((unsigned char)*end))end++;
        if(!number||*end||errno||(parsed!=0&&parsed!=1)){valid=0;break;}
        values[option]=(int)parsed;
    }
    if(ferror(file))valid=0;fclose(file);return valid;
}

int mw_fixes_init(int enabled){
    memset(options,0,sizeof options);memset(&timing,0,sizeof timing);
    clock_ready=0;previous=0;if(!enabled)return 1;
    int values[OPTIONS]={0};
    if(!read_options("scripts/MWFixes.ini",values,STABILITY,AICOP)||
       !read_options("scripts/ZPatchMW.ini",values,AICOP,OPTIONS))return 0;
    /* These three supplied options are disabled and have no native port. */
    if(values[TIMEBUG]||values[HANDLER]||values[BORDERLESS])return 0;
    memcpy(options,values,sizeof options);return 1;
}

int mw_fixes_branch(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_BRANCH(0x0043e005,0x0043e20c):
        if(!options[PURECALL])return 0;
        {uint32_t value=c->edx,result=value-0x00890970u;
         FLAGS_SUB(value,0x00890970u,result,32);if(result)return 0;}
        c->eax=0;FLAGS_LOG(0,32);return 1;
    case HOOK_BRANCH(0x0057d105,0x0057d11f):
        if(!options[STABILITY])return 0;
        FLAGS_LOG(c->ecx,32);return c->ecx==0;
    case HOOK_BRANCH(0x004549bf,0x00454a2a):
        if(!options[STABILITY])return 0;
        FLAGS_LOG(c->edi,32);if(c->edi)return 0;
        POP32(c->edi);POP32(c->esi);c->esp+=0x100;
        c->eax=0;FLAGS_LOG(0,32);return 1;
    case HOOK_BRANCH(0x004f0e7a,0x004f0e7f): {
        if(!options[AICOP])return 0;
        uint32_t a=MR32(c->esp),b=MR32(c->esp+4);double distance=99999.0;
        c->ecx=b;
        if(b!=0x40){
            c->eax=a;
            /* The ASI uses SUBSS then double MUL/ADD/SQRT, not x87 PC24. */
            double x=(float)(MRF32(a)-MRF32(b));
            double y=(float)(MRF32(a+4)-MRF32(b+4));
            double z=(float)(MRF32(a+8)-MRF32(b+8));
            volatile double xx=x*x,yy=y*y,zz=z*z,sum=yy+xx;
            distance=sqrt(sum+zz);
        }
        FPUSH(distance);return 1;
    }
    case HOOK_BRANCH(0x00642eaf,0x00642eda):return options[STUTTER];
    default:return -1;
    }
}

int mw_fixes_hook(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_SITE(0x00464eea):case HOOK_SITE(0x00464f4b):
        if(options[STABILITY]){c->eax=0;FLAGS_LOG(0,32);}return 1;
    case HOOK_SITE(0x00663dcd):
        if(options[STUTTER]){
            double elapsed=0;
            if(clock_ready){uint64_t sample=host_qpc();elapsed=((double)(sample-previous)/1000.0)*.001;previous=sample;}
            else clock_ready=1;
            if(elapsed<.001){
                const struct timespec delay={0,1000000L};
                guest_wait_begin();nanosleep(&delay,NULL);guest_wait_end();
            }
            timing.cpu=c;timing.stack=c->esp+4;timing.top=(c->top-1)&7;
        }
        return 1;
    case HOOK_SITE(0x00663dd2):
        if(options[STUTTER]&&timing.cpu==c&&timing.stack==c->esp&&timing.top==c->top){
            /* The original helper always calls 642e60 first; only frontend
             * return values are replaced, after the simulation side effects. */
            if((int32_t)MR32(0x00925e90)<=3)c->st[c->top&7]=(double)(float)((double)MRF32(0x009259bc)*1.5);
            timing.cpu=NULL;
        }
        return 1;
    default:return 0;
    }
}
