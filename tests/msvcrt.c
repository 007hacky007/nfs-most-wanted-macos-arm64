#include "cpu.h"
#include <assert.h>
#include <stdio.h>
void mem_init(void),mem_commit(uint32_t,uint32_t),heap_init(void);
uint32_t gheap_alloc(int,uint32_t,int);
int msvcrt_call(CPU *,const char *,uint32_t *);
long autotest_frame(void){return 0;}
void guest_backtrace(CPU *c,int n){(void)c;(void)n;}
static int callbacks;
uint32_t call_guest(CPU *c,uint32_t fn,int n,const uint32_t *args){
    (void)c;
    if(fn==0x12346){assert(n==2);return (uint32_t)((int32_t)MR32(args[0])-(int32_t)MR32(args[1]));}
    assert(fn==0x12345 && n==0); callbacks++; return 0;
}
int main(void){
    mem_init();heap_init();mem_commit(0x7f000000,0x10000);
    CPU cpu={0},*c=&cpu;c->esp=0x7f001000;
    uint32_t r=0,p;
    MR32(c->esp)=16;
    assert(msvcrt_call(c,"malloc",&r) && r);p=r;
    assert(c->esp==0x7f001000);memset(g_mem+p,0x42,16);
    MR32(c->esp)=p;MR32(c->esp+4)=32;
    assert(msvcrt_call(c,"realloc",&r) && r);
    for(int i=0;i<16;i++)assert(MR8(r+i)==0x42);
    MR32(c->esp)=r;assert(msvcrt_call(c,"free",&r));
    MR32(c->esp)=8;MR32(c->esp+4)=4;
    assert(msvcrt_call(c,"calloc",&r)&&r);
    for(int i=0;i<32;i++)assert(MR8(r+i)==0);
    MR32(c->esp)=0xffffffff;MR32(c->esp+4)=8;
    assert(msvcrt_call(c,"calloc",&r)&&r==0);
    uint32_t table=gheap_alloc(1,12,1);MR32(table)=0x12345;MR32(table+8)=0x12345;
    MR32(c->esp)=table;MR32(c->esp+4)=table+12;
    assert(msvcrt_call(c,"_initterm",&r)&&callbacks==2);
    uint32_t array=gheap_alloc(1,16,0);
    MR32(array)=4;MR32(array+4)=1;MR32(array+8)=3;MR32(array+12)=2;
    MR32(c->esp)=array;MR32(c->esp+4)=4;MR32(c->esp+8)=4;MR32(c->esp+12)=0x12346;
    assert(msvcrt_call(c,"qsort",&r));
    for(int i=0;i<4;i++)assert(MR32(array+4*i)==(uint32_t)i+1);
    c->fcw=0x027f;MR32(c->esp)=0;MR32(c->esp+4)=0;
    assert(msvcrt_call(c,"_controlfp",&r));
    assert((r&0x30000)==0x10000);
    MR32(c->esp)=0x20300;MR32(c->esp+4)=0x30300;
    assert(msvcrt_call(c,"_controlfp",&r));
    assert((c->fcw&0x0f00)==0x0c00 && (r&0x30300)==0x20300);
    strcpy((char *)g_mem+array,"AbC");strcpy((char *)g_mem+array+8,"aBc");
    MR32(c->esp)=array;MR32(c->esp+4)=array+8;
    assert(msvcrt_call(c,"_stricmp",&r)&&r==0);
    MR32(c->esp)=array+1;MR32(c->esp+4)=array;MR32(c->esp+8)=3;
    assert(msvcrt_call(c,"memmove",&r)&&r==array+1);
    assert(!memcmp(g_mem+array,"AAbC",4));
    assert(!msvcrt_call(c,"unimplemented",&r));
    puts("MSVCRT heap, cdecl stack, overflow and initializer callbacks passed");
}
