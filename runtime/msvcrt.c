/* Windows x86 CRT imports used by the lifted D3DX DLL. */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>

uint32_t gheap_alloc(int,uint32_t,int),gheap_usize(uint32_t);
void gheap_free(int,uint32_t);
uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
typedef struct {CPU *cpu;uint32_t function;} SortContext;
static int guest_compare(void *opaque,const void *a,const void *b){
    SortContext *context=opaque;
    uint32_t args[]={(uint32_t)((const uint8_t *)a-g_mem),(uint32_t)((const uint8_t *)b-g_mem)};
    return (int32_t)call_guest(context->cpu,context->function,2,args);
}

int msvcrt_call(CPU *c,const char *name,uint32_t *result){
    uint32_t a=MR32(c->esp),b=MR32(c->esp+4);
    *result=0;
    if (!strcmp(name,"malloc")||!strcmp(name,"??2@YAPAXI@Z"))
        *result=gheap_alloc(1,a,0);
    else if (!strcmp(name,"calloc")){
        if (!a || b <= UINT32_MAX/a) *result=gheap_alloc(1,a*b,1);
    } else if (!strcmp(name,"free")||!strcmp(name,"??3@YAXPAX@Z")) gheap_free(1,a);
    else if (!strcmp(name,"realloc")){
        if (!b){gheap_free(1,a);return 1;}
        uint32_t p=gheap_alloc(1,b,0);
        if (p && a){uint32_t old=gheap_usize(a);memcpy(g_mem+p,g_mem+a,old<b?old:b);gheap_free(1,a);}
        *result=p;
    } else if (!strcmp(name,"_initterm")){
        if (b<a || (b-a)%4 || b-a>0x100000){fprintf(stderr,"Invalid CRT initializer table\n");exit(78);}
        for(uint32_t p=a;p<b;p+=4) if(MR32(p)) call_guest(c,MR32(p),0,NULL);
    } else if (!strcmp(name,"_stricmp")) *result=(uint32_t)strcasecmp((char *)g_mem+a,(char *)g_mem+b);
    else if (!strcmp(name,"memmove")){
        memmove(g_mem+a,g_mem+b,MR32(c->esp+8));*result=a;
    } else if (!strcmp(name,"_controlfp")){
        static const uint32_t masks[]={0x10,0x80000,8,4,2,1};
        uint32_t old=0;
        for(int i=0;i<6;i++)if(c->fcw&(1u<<i))old|=masks[i];
        old|=((uint32_t)c->fcw&0x0c00u)>>2;
        old|=(c->fcw&0x0300u)==0?0x20000u:(c->fcw&0x0300u)==0x0200u?0x10000u:0;
        if(c->fcw&0x1000u)old|=0x40000u;
        b&=~0x80000u;
        uint32_t updated=(old&~b)|(a&b);
        uint16_t word=c->fcw&~0x1f3fu;
        for(int i=0;i<6;i++)if(updated&masks[i])word|=1u<<i;
        word|=(updated&0x300u)<<2;
        word|=(updated&0x30000u)==0x20000u?0:(updated&0x30000u)==0x10000u?0x0200u:0x0300u;
        if(updated&0x40000u)word|=0x1000u;
        c->fcw=word;*result=updated;
    } else if (!strcmp(name,"qsort")){
        uint32_t size=MR32(c->esp+8),fn=MR32(c->esp+12);
        if(size && b>UINT32_MAX/size){fprintf(stderr,"Invalid guest qsort extent\n");exit(78);}
        if(b>1 && size){SortContext context={c,fn};qsort_r(g_mem+a,b,size,&context,guest_compare);}
    } else return 0;
    return 1;
}
