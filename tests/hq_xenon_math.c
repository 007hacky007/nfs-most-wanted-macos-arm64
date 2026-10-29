#include "cpu.h"
#include <assert.h>
#include <errno.h>
#include <fenv.h>
#include <stdlib.h>
int hq_xenon_math_call(CPU*,const char*,uint32_t*);
uint8_t *g_mem;
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
static unsigned calls;
void dispatch_indirect(CPU*c,uint32_t target){
 assert(target==0x03000100);POP32(c->eip);assert(c->eip==0x02409501);
 assert(MR32(c->esp)==0x42280000);uint32_t result=99,stack=c->esp;
 assert(hq_xenon_math_call(c,"fminf",&result)==1&&result==0&&c->esp==stack);
 c->eax=result;calls++;
}
#include "fragment.inc"
static void direct(uint32_t first,uint32_t second,float expected,int negative_zero){
 for(unsigned top=0;top<8;top++){
  CPU cpu={0},*c=&cpu;c->esp=0x1000;c->top=top;c->eax=123;c->ecx=456;
  c->cf=1;c->zf=1;c->fcw=0x037f;c->fsw=0x21;
  for(unsigned i=0;i<8;i++)c->st[i]=100+i;
  MR32(c->esp)=first;MR32(c->esp+4)=second;
  CPU before=*c;uint32_t result=99;errno=EDOM;feclearexcept(FE_ALL_EXCEPT);
  assert(hq_xenon_math_call(c,"fminf",&result)==1&&result==0);
  assert(errno==EDOM&&fetestexcept(FE_ALL_EXCEPT)==0);
  if(isnan(expected))assert(isnan(ST(0)));else assert(ST(0)==expected);
  if(negative_zero)assert(signbit(ST(0)));
  before.top=(top-1)&7;before.st[before.top]=ST(0);
  assert(!memcmp(c,&before,sizeof before));
  assert(MR32(c->esp)==first&&MR32(c->esp+4)==second);
 }
}
int main(void){
 g_mem=calloc(1,0x03010000);assert(g_mem);
 direct(0x42280000,0x41a80000,21,0);direct(0x42280000,0x42c80000,42,0);
 direct(0x42280000,0xc1280000,-10.5f,0);direct(0x42280000,0x80000000,-0.0f,1);
 direct(0x42280000,0x00000000,0,0);direct(0x42280000,0x7f800000,42,0);
 direct(0x42280000,0xff800000,-INFINITY,0);
 direct(0x42280000,0x7fc12345,42,0);direct(0x42280000,0x7f800001,42,0);
 direct(0x7f800001,0x42280000,42,0);direct(0x7fc12345,0x7f800001,NAN,0);
 CPU untouched={0},before=untouched;uint32_t result=99;
 assert(!hq_xenon_math_call(&untouched,"fmaxf",&result));
 assert(result==99&&!memcmp(&untouched,&before,sizeof before));
#if ACTUAL_CALLER
 const float inputs[]={0,.125f,.5f,.999f,1,1.5f,-.5f};
 MR32(0x240d128)=0x03000100;MRF32(0x240fe80)=42;
 for(unsigned i=0;i<sizeof inputs/sizeof *inputs;i++){
  CPU cpu={0},*c=&cpu;c->esp=0x2000;c->top=i%8;c->fcw=0x027f;
  c->xmm[2].f[0]=inputs[i];MRF32(c->esp+0x20)=13.5f;
  MR32(c->esp)=0xdeadbeef;unsigned before_top=c->top;
  sub_024094e0(c);
  float expected=inputs[i]*42;if(expected>42)expected=42;
  assert(c->esp==0x2004&&c->eip==0xdeadbeef&&c->top==before_top);
  assert(MRF32(0x201c)==expected&&(int32_t)c->edi==(int32_t)expected);
  assert(c->xmm[2].f[0]==13.5f);
 }
 assert(calls==7);
#endif
 free(g_mem);return 0;
}
