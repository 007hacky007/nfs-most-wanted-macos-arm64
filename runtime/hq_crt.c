/* Modern CRT ABI used by the pinned ASI. Unimplemented C++/SEH calls fail in win32_call. */
#include "hq_crt.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <time.h>
uint32_t gheap_alloc(int,uint32_t,int),gheap_usize(uint32_t);
void gheap_free(int,uint32_t);
uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
uint32_t guest_vformat(uint32_t,uint32_t,const char *,uint32_t);
int msvcrt_call(CPU *,const char *,uint32_t *);
static uint32_t exit_table;
static _Thread_local uint32_t errno_data;

int hq_crt_dll(const char *dll){
    return !strcasecmp(dll,"MSVCP140.dll")||!strcasecmp(dll,"VCRUNTIME140.dll")
        ||!strncasecmp(dll,"api-ms-win-crt-",15)||!strcasecmp(dll,"ucrtbase.dll");
}
void hq_crt_thread_detach(void){if(errno_data){gheap_free(1,errno_data);errno_data=0;}}
static int onexit_add(uint32_t table,uint32_t fn){
    uint32_t begin=MR32(table),last=MR32(table+4),end=MR32(table+8);
    if(!begin){begin=gheap_alloc(1,64*4,1);if(!begin)return -1;last=begin;end=begin+64*4;}
    if(last<begin||last>end||(last-begin)%4)return -1;
    if(last==end){uint32_t size=end-begin,p=gheap_alloc(1,size*2,1);if(!p)return -1;
        memcpy(g_mem+p,g_mem+begin,size);gheap_free(1,begin);last=p+size;begin=p;end=p+size*2;}
    MR32(last)=fn;last+=4;MR32(table)=begin;MR32(table+4)=last;MR32(table+8)=end;return 0;
}
static int onexit_run(CPU *c,uint32_t table){
    uint32_t begin=MR32(table),last=MR32(table+4);
    if(last<begin||(last-begin)%4||last-begin>0x100000)return -1;
    while(last>begin){last-=4;MR32(table+4)=last;if(MR32(last))call_guest(c,MR32(last),0,NULL);}
    if(begin)gheap_free(1,begin);memset(g_mem+table,0,12);return 0;
}
static void save_errno(void){if(errno_data)MR32(errno_data)=(uint32_t)errno;}
int hq_crt_call(CPU *c,const char *name,uint32_t *result){
    uint32_t a=MR32(c->esp),b=MR32(c->esp+4),d=MR32(c->esp+8);*result=0;
    if(!strcmp(name,"_initterm")||!strcmp(name,"_initterm_e")){
        if(b<a||(b-a)%4||b-a>0x100000){fprintf(stderr,"Invalid ASI CRT initializer extent\n");exit(78);}
        for(uint32_t p=a;p<b;p+=4)if(MR32(p)){
            uint32_t r=call_guest(c,MR32(p),0,NULL);if(!strcmp(name,"_initterm_e")&&r){*result=r;break;}}
    }else if(!strcmp(name,"_initialize_onexit_table"))memset(g_mem+a,0,12);
    else if(!strcmp(name,"_register_onexit_function"))*result=(uint32_t)onexit_add(a,b);
    else if(!strcmp(name,"_execute_onexit_table"))*result=(uint32_t)onexit_run(c,a);
    else if(!strcmp(name,"_crt_atexit")){
        if(!exit_table)exit_table=gheap_alloc(1,12,1);
        *result=exit_table?(uint32_t)onexit_add(exit_table,a):0xffffffffu;
    }else if(!strcmp(name,"_cexit")){if(exit_table)*result=(uint32_t)onexit_run(c,exit_table);}
    else if(!strcmp(name,"_configure_narrow_argv")){if(a>2)*result=22;}
    else if(!strcmp(name,"_initialize_narrow_environment")){}
    else if(!strcmp(name,"memcpy")||!strcmp(name,"memmove")){memmove(g_mem+a,g_mem+b,d);*result=a;}
    else if(!strcmp(name,"memset")){memset(g_mem+a,(int)b,d);*result=a;}
    else if(!strcmp(name,"strncmp"))*result=(uint32_t)strncmp((char*)g_mem+a,(char*)g_mem+b,d);
    else if(!strcmp(name,"tolower"))*result=(uint32_t)tolower((int)(int32_t)a);
    else if(!strcmp(name,"toupper"))*result=(uint32_t)toupper((int)(int32_t)a);
    else if(!strcmp(name,"strtol")){char *end=NULL;errno=0;long value=strtol((char*)g_mem+a,&end,(int)d);
        if(value>INT32_MAX){value=INT32_MAX;errno=ERANGE;}if(value<INT32_MIN){value=INT32_MIN;errno=ERANGE;}
        if(b)MR32(b)=(uint32_t)((uint8_t*)end-g_mem);*result=(uint32_t)value;save_errno();}
    else if(!strcmp(name,"strtof")){char *end=NULL;errno=0;float value=strtof((char*)g_mem+a,&end);
        if(b)MR32(b)=(uint32_t)((uint8_t*)end-g_mem);FPUSH(value);save_errno();}
    else if(!strcmp(name,"_errno")){if(!errno_data)errno_data=gheap_alloc(1,4,1);*result=errno_data;}
    else if(!strcmp(name,"_aligned_malloc")){
        uint32_t align=b<4?4:b;if(!b||(b&(b-1))||a>UINT32_MAX-align-4){*result=0;return 1;}
        uint32_t p=gheap_alloc(1,a+align+4,0);if(p){uint32_t aligned=(p+4+align-1)&~(align-1);MR32(aligned-4)=p;*result=aligned;}
    }else if(!strcmp(name,"_aligned_free")){if(a)gheap_free(1,MR32(a-4));}
    else if(!strcmp(name,"__libm_sse2_tanf"))c->xmm[0].f[0]=tanf(c->xmm[0].f[0]);
    else if(!strcmp(name,"_CIfmod")){double v=fmod(ST(1),ST(0));FPOP();ST(0)=v;}
    else if(!strcmp(name,"ceil")){double v=ceil(MRF64(c->esp));FPUSH(v);}
    else if(!strcmp(name,"fmaxf")){float v=fmaxf(MRF32(c->esp),MRF32(c->esp+4));FPUSH(v);}
    else if(!strcmp(name,"_Xtime_get_ticks")){
        struct timespec time;clock_gettime(CLOCK_REALTIME,&time);
        uint64_t ticks=(uint64_t)time.tv_sec*10000000ull+(uint64_t)time.tv_nsec/100;
        *result=(uint32_t)ticks;c->edx=(uint32_t)(ticks>>32);
    }else if(!strcmp(name,"__stdio_common_vsprintf")){
        uint32_t out=d,cap=MR32(c->esp+12),fmt=MR32(c->esp+16),va=MR32(c->esp+24);
        uint32_t n=guest_vformat(out,cap,(char*)g_mem+fmt,va);*result=n;
    }else if(!strcmp(name,"__std_type_info_destroy_list")){
        if(MR32(a)||MR32(a+4))return 0;
    }else if(!strcmp(name,"_CxxThrowException")||!strcmp(name,"__CxxFrameHandler3")
            ||!strcmp(name,"_except_handler4_common")||!strcmp(name,"__std_terminate")
            ||!strcmp(name,"_invoke_watson")||!strncmp(name,"?_X",3)){
        fprintf(stderr,"ASI reached unsupported C++ exception/SEH path: %s\n",name);exit(78);
    }else return msvcrt_call(c,name,result);
    return 1;
}
