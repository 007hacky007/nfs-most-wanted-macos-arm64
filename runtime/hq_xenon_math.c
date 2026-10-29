/* Pinned Xenon cdecl fminf import; ESP already points at its two float arguments. */
#include "cpu.h"
int hq_xenon_math_call(CPU *c,const char *name,uint32_t *result){
    if(strcmp(name,"fminf"))return 0;
    uint32_t x=MR32(c->esp),y=MR32(c->esp+4),selected=x;
    /* Inspect NaNs before float conversion so signaling inputs raise no host exception. */
    if((x&0x7fffffffu)>0x7f800000u)selected=y;
    else if((y&0x7fffffffu)<=0x7f800000u){
        uint32_t a=(x&0x80000000u)?~x:(x^0x80000000u);
        uint32_t b=(y&0x80000000u)?~y:(y^0x80000000u);
        if(b<a)selected=y;
    }
    if((selected&0x7fffffffu)>0x7f800000u)selected|=0x00400000u;
    float value;memcpy(&value,&selected,4);FPUSH(value);
    *result=0;return 1;
}
