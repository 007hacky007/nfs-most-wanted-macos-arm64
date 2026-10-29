/* Bounded host interfaces for preparing original, locally lifted HQ writers. */
#include "hq_prepare.h"
#include "hq_capture.h"
#include "hq_plugin.h"
#include "kbd.h"
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>

uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
uint32_t gheap_alloc(int,uint32_t,int);
void gheap_free(int,uint32_t);
void dispatch_patch(uint32_t,guest_fn_t);
int fileio_resolve_game(const char *,char *,size_t);

enum { PREP_NONE,PREP_BOOT,PREP_XENON,PREP_CARS,PREP_EO };
static struct { unsigned phase; CPU *cpu; jmp_buf stop; } preparation;

static int readable(uint32_t address,uint32_t size){
    if(!size||(uint64_t)address+size>0x100000000ull)return 0;
    uint64_t end=(uint64_t)address+size;
    for(uint64_t p=address;p<end;p=(p|0x3fffull)+1)
        if(!mem_is_committed((uint32_t)p))return 0;
    return 1;
}

static void prepare_stop(CPU *c,int accepted,const char *reason,uint32_t address){
    if(accepted)hq_capture(c,reason,address);
    else fprintf(stderr,"HQ preparation refused an unexpected boundary in phase %u\n",preparation.phase);
    longjmp(preparation.stop,accepted?1:2);
}

void hq_prepare_import(CPU *c,const char *name){
    if(!preparation.phase||c!=preparation.cpu)return;
    if(!strcmp(name,"CreateThread")){
        int expected=preparation.phase==PREP_BOOT&&readable(c->esp,16)&&
                     MR32(c->esp)==0x01007adeu&&MR32(c->esp+12)==0x01007b10u;
        prepare_stop(c,expected,"boot",0x01007adeu);
    }
    if(!strncmp(name,"CreateWindow",12)||!strcmp(name,"CreateRemoteThread"))
        prepare_stop(c,0,NULL,0);
}

void hq_prepare_checkpoint(CPU *c,unsigned point){
    if(!preparation.phase||c!=preparation.cpu)return;
    if(preparation.phase==PREP_CARS)
        prepare_stop(c,point==1,"cartypes",0x0180adcau);
    if(preparation.phase==PREP_EO)
        prepare_stop(c,point==3,"eohotkeys",0x01c04a50u);
}

static int prepare_call(CPU *c,unsigned phase,uint32_t function,int argc,
                        const uint32_t *arguments,uint32_t esi){
    if(!c||preparation.phase||!readable(c->fs_base,4)||
       !readable(c->esp-32,64))return 0;
    CPU saved=*c;
    uint32_t seh=MR32(saved.fs_base);
    preparation.phase=phase;preparation.cpu=c;
    int stopped=setjmp(preparation.stop);
    if(!stopped){
        if(phase==PREP_CARS)c->esi=esi;
        call_guest(c,function,argc,arguments);
        if(phase==PREP_XENON){
            /* The original process-name check may return zero after config. */
            hq_capture(c,"xenoninit",0x02404370u);
            stopped=1;
        }else fprintf(stderr,"HQ preparation did not reach its required boundary in phase %u\n",phase);
    }
    /* longjmp bypasses call_guest's CPU restore and the guest's SEH epilogue. */
    *c=saved;MR32(saved.fs_base)=seh;
    preparation.phase=PREP_NONE;preparation.cpu=NULL;
    return stopped==1;
}

static struct { uint32_t vehicle,player,sim; unsigned glare; } eo;
static const uint32_t eo_targets[]={0x005983c0u,0x006881c0u,0x00669360u,0x00669380u};
static const struct { uint32_t address,size; } eo_globals[]={
    {0x0091cf90u,4},{0x0092cd24u,4},{0x0092cd28u,4},
    {0x0092d888u,4},{0x00925e90u,4},{0x00982c50u,1}
};

static void eo_return(CPU *c,uint32_t value,unsigned clean){
    c->eax=value;POP32(c->eip);c->esp+=clean;
}
static void eo_dialog(CPU *c){
    if(!readable(c->esp,8))prepare_stop(c,0,NULL,0);
    uint32_t text=MR32(c->esp+4);
    if(!readable(text,1)||!MR8(text))prepare_stop(c,0,NULL,0);
    eo_return(c,1,0);
}
static void eo_simable(CPU *c){
    if(c->ecx!=eo.player&&c->ecx!=eo.vehicle)prepare_stop(c,0,NULL,0);
    eo_return(c,eo.sim,0);
}
static int eo_vehicle_arg(CPU *c){
    return c->ecx==eo.vehicle&&readable(c->esp,8)&&MR32(c->esp+4)==7;
}
static void eo_glare_query(CPU *c){
    if(!eo_vehicle_arg(c))prepare_stop(c,0,NULL,0);
    eo_return(c,eo.glare,4);
}
static void eo_glare_on(CPU *c){
    if(!eo_vehicle_arg(c))prepare_stop(c,0,NULL,0);
    eo.glare=1;eo_return(c,0,4);
}
static void eo_glare_off(CPU *c){
    if(!eo_vehicle_arg(c))prepare_stop(c,0,NULL,0);
    eo.glare=0;eo_return(c,0,4);
}

static int prepare_eo(CPU *c){
    uint8_t saved[sizeof eo_globals/sizeof *eo_globals][4];
    guest_fn_t handlers[sizeof eo_targets/sizeof *eo_targets];
    for(unsigned i=0;i<sizeof eo_globals/sizeof *eo_globals;i++){
        if(!readable(eo_globals[i].address,eo_globals[i].size))return 0;
        memcpy(saved[i],g_mem+eo_globals[i].address,eo_globals[i].size);
    }
    for(unsigned i=0;i<sizeof eo_targets/sizeof *eo_targets;i++)handlers[i]=dispatch_fast(eo_targets[i]);
    uint32_t memory=gheap_alloc(1,0x680,1);
    if(!memory)return 0;
    uint32_t options=memory,career=memory+0x400,vtable=memory+0x660;
    eo.vehicle=memory+0x600;eo.player=memory+0x620;eo.sim=memory+0x640;eo.glare=1;
    MR32(options+0x10)=career;MR8(options+0x12c)=4;
    MR32(options+0x2c)=0x12345678u;MR32(career+0xa8)=0x87654321u;
    MR32(vtable+4)=0xc1001000u;MR32(eo.vehicle)=vtable;MR32(eo.player)=vtable;
    MR32(0x0091cf90u)=options;MR32(0x0092cd24u)=1;MR32(0x0092cd28u)=eo.vehicle;
    MR32(0x0092d888u)=eo.player;MR32(0x00925e90u)=6;MR8(0x00982c50u)=0;
    dispatch_patch(0xc1001000u,eo_simable);
    dispatch_patch(eo_targets[0],eo_dialog);dispatch_patch(eo_targets[1],eo_glare_query);
    dispatch_patch(eo_targets[2],eo_glare_on);dispatch_patch(eo_targets[3],eo_glare_off);
    /* Gray-code traversal changes one original hotkey at each callback. */
    const unsigned keys[]={0,0x3e,0x23,0x3e,0x41,0x3e,0x23,0x3e};
    int ok=1;
    for(unsigned i=0;i<sizeof keys/sizeof *keys&&ok;i++){
        if(keys[i])kbd_set_key(KSRC_SCRIPT,keys[i],1);
        ok=prepare_call(c,PREP_EO,0x01c04a50u,0,NULL,0);
        if(keys[i])kbd_set_key(KSRC_SCRIPT,keys[i],0);
    }
    dispatch_patch(0xc1001000u,NULL);
    for(unsigned i=0;i<sizeof eo_targets/sizeof *eo_targets;i++)dispatch_patch(eo_targets[i],handlers[i]);
    for(unsigned i=0;i<sizeof eo_globals/sizeof *eo_globals;i++)
        memcpy(g_mem+eo_globals[i].address,saved[i],eo_globals[i].size);
    gheap_free(1,memory);
    return ok;
}

static uint32_t load_car_types(void){
    char path[4096];
    if(!fileio_resolve_game("GLOBAL/GlobalB.lzc",path,sizeof path))return 0;
    FILE *file=fopen(path,"rb");if(!file)return 0;
    /* The supported HQ asset has one original 97-row CarTypes chunk here. */
    enum { HEADER_OFFSET=0x00fa9e50,CHUNK_SIZE=16+97*208 };
    uint8_t data[CHUNK_SIZE];
    int ok=!fseek(file,HEADER_OFFSET,SEEK_SET)&&fread(data,1,sizeof data,file)==sizeof data;
    fclose(file);if(!ok)return 0;
    uint32_t id,size;
    memcpy(&id,data,4);memcpy(&size,data+4,4);
    if(id!=0x00034600u||size!=8+97*208)return 0;
    uint32_t chunk=gheap_alloc(1,sizeof data,0);
    if(!chunk)return 0;
    memcpy(g_mem+chunk,data,sizeof data);
    return chunk;
}

int hq_prepare_run(CPU *c){
    if(!c||!hq_plugin_enabled()||preparation.phase)return 0;
    uint32_t cars=load_car_types();if(!cars){fprintf(stderr,"HQ preparation requires the verified 97-row car asset\n");return 0;}
    const uint32_t xenon_arguments[]={0x008a9160u,1u};
    int ok=prepare_call(c,PREP_BOOT,MW_ENTRY,0,NULL,0)&&
           prepare_call(c,PREP_XENON,0x02404940u,2,xenon_arguments,0)&&
           prepare_call(c,PREP_CARS,0x0180ad50u,0,NULL,cars+16)&&prepare_eo(c);
    gheap_free(1,cars);
    if(ok)fprintf(stderr,"HQ_RUNTIME_PREPARATION_OK no guest threads, window or graphics device\n");
    return ok;
}
