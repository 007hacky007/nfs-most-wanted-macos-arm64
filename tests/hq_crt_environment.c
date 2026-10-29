#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

uint8_t *g_mem;
static uint16_t expected_control,next_control,next_status;
#include "adapted.c"

static void untouched_frame(void){
    for(unsigned i=0;i<0x80;i++){
        uint32_t address=0x1fc0+i;
        if(address>=0x1fe0&&address<0x1fe8)continue;
        assert(g_mem[address]==0xa5);
    }
}

#ifndef HQ_ACTUAL_CRT_ENVIRONMENT
int main(void){
    g_mem=calloc(1,0x4000);assert(g_mem);CPU cpu={0},*c=&cpu;c->ebp=0x2000;
    for(unsigned i=0;i<8;i++)c->st[i]=i+.125;
    double original[8];memcpy(original,c->st,sizeof original);
    const unsigned precision[]={0,2,3};
    for(unsigned top=0;top<8;top++)for(unsigned mask=0;mask<64;mask++)
        for(unsigned pc=0;pc<3;pc++)for(unsigned rounding=0;rounding<4;rounding++){
            memset(g_mem+0x1fc0,0xa5,0x80);c->top=top;
            expected_control=(uint16_t)(0x40|mask|(precision[pc]<<8)|(rounding<<10));
            c->fcw=expected_control;c->fsw=0x4500|(mask^0x3f);uint16_t status=fsw_get(c);
            sub_01c2dac7(c);
            assert(c->fcw==expected_control&&fsw_get(c)==status&&c->top==top);
            assert(MR32(0x1fe0)==expected_control&&MR32(0x1fe4)==status);
            untouched_frame();assert(!memcmp(c->st,original,sizeof original));
            next_control=(uint16_t)(expected_control^0x0c3f);sub_01c2dbf1(c);
            assert(c->fcw==next_control&&fsw_get(c)==status&&c->top==top);
            untouched_frame();assert(!memcmp(c->st,original,sizeof original));
            next_status=(uint16_t)(0x4500|(((top+1)&7)<<11)|mask);
            sub_01c2dc6c(c);
            assert(c->fcw==next_control&&fsw_get(c)==next_status&&c->top==((top+1)&7));
            untouched_frame();assert(!memcmp(c->st,original,sizeof original));
        }
    free(g_mem);puts("6144 represented environment roundtrips with frame guards passed");return 0;
}

#else
static void call(CPU *c,guest_fn_t function,int argument,uint32_t value){
    uint32_t esp=c->esp,ebp=c->ebp,ebx=c->ebx,esi=c->esi,edi=c->edi;
    if(argument)PUSH32(value);PUSH32(0xdeadbeef);function(c);
    assert(c->eip==0xdeadbeef&&c->esp==esp-(argument?4:0));
    assert(c->ebp==ebp&&c->ebx==ebx&&c->esi==esi&&c->edi==edi);
    if(argument)c->esp+=4;
}
void unsupported_insn(CPU*c,uint32_t address,const char*opcode){
    (void)c;fprintf(stderr,"unexpected instruction %08x %s\n",address,opcode);abort();
}
int main(int argc,char **argv){
    assert(argc==2);g_mem=calloc(1,0x02000000);assert(g_mem);
    FILE *file=fopen(argv[1],"rb");assert(file);
    assert(fread(g_mem+0x01c00000,1,0x48000,file)==0x48000);fclose(file);
    CPU cpu={0},*c=&cpu;c->esp=0x00f00000;c->ebp=0x1234;c->ebx=0x2345;c->esi=0x3456;c->edi=0x4567;
    c->fcw=0x027f;c->fsw=0x4500;c->top=5;
    for(unsigned i=0;i<8;i++)c->st[i]=i+.125;
    double original[8];memcpy(original,c->st,sizeof original);unsigned precision[]={0,2,3};
    for(unsigned sse=0;sse<2;sse++)for(unsigned mask=0;mask<64;mask++)
        for(unsigned pc=0;pc<3;pc++)for(unsigned rounding=0;rounding<4;rounding++){
            MR32(0x01c423c4)=sse;
            uint16_t control=(uint16_t)(0x40|mask|(precision[pc]<<8)|(rounding<<10));
            c->fcw=control;uint16_t status=fsw_get(c);call(c,sub_01c2dac7,0,0);uint32_t encoded=c->eax;
            assert(c->fcw==control&&fsw_get(c)==status&&c->top==5&&!memcmp(c->st,original,sizeof original));
            c->fcw=0x027f;call(c,sub_01c2dbf1,1,encoded);
            assert(c->fcw==control&&fsw_get(c)==status&&c->top==5&&!memcmp(c->st,original,sizeof original));
        }
    for(unsigned bit=0;bit<6;bit++){
        uint16_t control=c->fcw,condition=fsw_get(c)&~0x3f;
        MR32(0x01c423c4)=0;c->fsw=condition|(1u<<bit);call(c,sub_01c2db47,0,0);uint32_t encoded=c->eax;
        c->fsw=condition;call(c,sub_01c2dc6c,1,encoded);
        assert(c->fcw==control&&fsw_get(c)==(condition|(1u<<bit))&&c->top==5&&!memcmp(c->st,original,sizeof original));
    }
    free(g_mem);puts("1536 actual CRT control cases and 6 exception cases passed");return 0;
}
#endif
