#include "../runtime/com.c"
#include <assert.h>
#include <sys/mman.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];int g_gh_com,g_gh_gbuf,g_fxtr,g_dx_in_pass;
uint64_t g_icall_hits;
int g_perflog;
uint64_t g_timer_ticks;
int gheap_bump(void){return 1;}
void mem_commit(uint32_t address,uint32_t size){
    for(uint64_t a=address;a<(uint64_t)address+size;a+=4096){uint32_t page=(uint32_t)a>>14;g_cbits[page>>3]|=1u<<(page&7);}
    uint32_t page=(address+size-1)>>14;g_cbits[page>>3]|=1u<<(page&7);
}
static int metal_on;
int metal_available(void){return metal_on;}
static uint32_t invoke(CPU *cpu,int iface,const char *method,uint32_t self,const uint32_t *args){
    unsigned slot=0;while(slot<g_if[iface].n && strcmp(g_if[iface].m[slot].name,method))slot++;
    assert(slot<g_if[iface].n);cpu->esp=0x10000;MR32(cpu->esp)=0x1234;MR32(cpu->esp+4)=self;
    for(unsigned i=1;i<g_if[iface].m[slot].nargs;i++)MR32(cpu->esp+4+i*4)=args[i-1];
    assert(com_call(cpu,COM_MAGIC|(iface<<16)|slot));
    assert(cpu->esp==0x10004+4*g_if[iface].m[slot].nargs);return cpu->eax;
}


void metal_query_reset(void){}

static unsigned postfx_calls,postfx_source,postfx_gamma,postfx_border,effective_samples=1;
unsigned metal_widescreen_samples(unsigned target){return target?1:effective_samples;}
void metal_widescreen_postfx(unsigned source,unsigned gamma,unsigned border){postfx_calls++;postfx_source=source;postfx_gamma=gamma;postfx_border=border;}
int main(void){
 g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
 CPU cpu={0};uint32_t device=com_new(IF_DEV,32);g_dev=device;metal_on=1;rs_defaults();assert(g_rs[161]==1);g_rs[161]=0;
 unsigned saved[256];memcpy(saved,g_rs,sizeof saved);com_widescreen_postfx(0,0);assert(!postfx_calls);
 com_widescreen_postfx(0,2);assert(!postfx_calls&&g_ws_msaa_checked);
 g_rs[161]=1;com_widescreen_postfx(0,2);assert(!postfx_calls); /* cached until Reset */
 g_rs[161]=0;com_widescreen_postfx(1,2);assert(postfx_calls==1&&postfx_gamma==1&&postfx_border==0&&postfx_source==0);
 assert(!memcmp(saved,g_rs,sizeof saved));
 uint32_t surface=com_new(IF_SURF,64);MR32(surface+44)=4;g_bind_rt[0]=surface;g_cur_rt=29;
 com_widescreen_postfx(2,0);assert(postfx_calls==2&&postfx_source==(29|(4u<<16))&&postfx_gamma==2&&!postfx_border);
 g_bind_rt[0]=0;g_cur_rt=0;
 uint32_t args[4]={0};metal_on=0;assert(!invoke(&cpu,IF_DEV,"Reset",device,args));assert(!g_ws_msaa_checked);metal_on=1;
 rs_defaults();g_rs[161]=0;effective_samples=4;com_widescreen_postfx(0,2);assert(postfx_calls==3&&postfx_border==2);
 effective_samples=1;com_widescreen_postfx(0,1);assert(postfx_calls==4&&postfx_border==1); /* cached positive too */
 uint32_t pp=0x19000;mem_commit(pp,56);memset(g_mem+pp,0,56);MR32(pp+16)=4;args[0]=pp;metal_on=0;
 assert(!invoke(&cpu,IF_DEV,"Reset",device,args));metal_on=1;rs_defaults();g_rs[161]=0;
 com_widescreen_postfx(0,2);assert(postfx_calls==5&&postfx_border==2&&g_ws_present_samples==4);
 com_widescreen_postfx(3,1);com_widescreen_postfx(1,3);metal_on=0;com_widescreen_postfx(1,2);assert(postfx_calls==5);
 puts("WS COM: RT/cube snapshot, MSAA fallback/cache/Reset, disabled and render-state preservation passed");return 0;
}
