#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

uint8_t *g_mem;
static int cleanup;
uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
void dispatch_indirect(CPU *c,uint32_t fn){
    assert(fn==0x123456u);
    assert(MR32(c->esp)==0xdeadbeefu);
    assert(MR32(c->esp+4)==11 && MR32(c->esp+8)==22);
    MR32(0x100)=33;
    c->eax=77; c->ecx=0; c->st[c->top]=9.;
    c->esp+=4+(cleanup?8:0);
}

int main(void){
    g_mem=calloc(1,0x10000);
    assert(g_mem);
    CPU c={0}; c.esp=0xff00; c.ecx=0x5555; c.fcw=0x027f; c.st[0]=3.5;
    CPU before=c;
    uint32_t args[]={11,22};
    for(cleanup=0;cleanup<2;cleanup++){
        assert(call_guest(&c,0x123456,2,args)==77);
        assert(!memcmp(&c,&before,sizeof c));
        assert(MR32(0x100)==33);
    }
    assert(call_guest(&c,0,0,NULL)==0);
    free(g_mem);
    puts("ABI callbacks: cdecl/stdcall arguments, CPU and x87 preservation passed");
}
