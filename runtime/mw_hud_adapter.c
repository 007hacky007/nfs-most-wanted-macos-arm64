/* HUD Adapter 1.0.0.800, supplied ASI ab9c6e4939ae7e2bca628d795d2478c2
 * c11d15e2a18554f93223960b94bcd137. Two package callbacks and three minimap
 * operands match nlgxzef/NFSMWHUDAdapter/dllmain.cpp.
 */
#include "cpu.h"
#include "widescreen.h"
#define HOOK_BRANCH(a,b) a

uint32_t gheap_alloc(int,uint32_t,int);
uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
static int active,positioned;
static uint32_t center;
static float difference;

int mw_hud_adapter_init(int enabled){
    active=positioned=0;center=0;difference=0;
    if(!enabled)return 1;
    center=gheap_alloc(1,8,1);if(!center)return 0;
    active=1;return 1;
}

static void adapt(CPU *c){
    CPU saved=*c;uint32_t package=MR32(c->esp+4);
    /* Use the actual device aspect, also used by native widescreen, because
     * the game can keep its logical canvas while Metal draws at another size. */
    float aspect=ws_aspect_ratio();volatile float scaled=aspect*240.f;
    difference=isfinite(aspect)&&aspect>0?scaled-320.f:0;positioned=1;
    const uint32_t hashes[]={0x1603009eu,0x5d0101f1u};
    for(unsigned i=0;i<2;i++){
        uint32_t find[]={package,hashes[i]};
        uint32_t object=call_guest(c,0x00524850,2,find);*c=saved;
        if(!object)continue;
        uint32_t get[]={object,center,center+4};
        call_guest(c,0x00524ee0,3,get);*c=saved;
        float x=MRF32(center)+(i?difference:-difference);uint32_t bits;
        memcpy(&bits,&x,4);uint32_t set[]={object,bits,MR32(center+4)};
        call_guest(c,0x00525050,3,set);*c=saved;
    }
    c->eax=1;c->esp+=12; /* Replaced callback: stdcall with three slots. */
}

int mw_hud_adapter_branch(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_BRANCH(0x005696f1,0x005696f6):
    case HOOK_BRANCH(0x00569712,0x00569717):
        if(!active)return 0;adapt(c);return 1;
    default:return -1;
    }
}

int mw_hud_adapter_hook(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_SITE(0x005678ae):if(active&&positioned)c->st[c->top&7]=-(double)difference;return 1;
    case HOOK_SITE(0x005678b8):if(active&&positioned)MRF32(0x0091cf04)=-difference;return 1;
    case HOOK_SITE(0x005678ca):if(active&&positioned)c->st[c->top&7]=(double)difference;return 1;
    default:return 0;
    }
}
