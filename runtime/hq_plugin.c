#include "hq_plugin.h"
#include "hq_config.h"
#include "hq_xenon_fields.h"
#include "hq_tls.h"
#include "hq_capture.h"
#include "hq_audio.h"
#include "hq_prepare.h"
int ws_high_spec_audio(void);
#include "module.h"
#include <stdio.h>
#include <stdlib.h>
static int enabled;
static uint8_t config[HQ_CONFIG_SIZE];
static uint32_t id_count,codecvt_id;
uint32_t gheap_alloc(int,uint32_t,int);
int fileio_resolve_game(const char *,char *,size_t);
int hq_plugin_enabled(void){return enabled;}
void hq_plugin_thread(CPU *c){
    if(enabled&&!hq_tls_attach(c)){fprintf(stderr,"ASI per-thread TLS unavailable\n");exit(78);}
}
int hq_plugin_module_mapped(CPU *c,uint32_t base){
    uint32_t data,size,index,slot;
    if(!module_static_tls(base,&data,&size,&index,&slot))return 1;
    return hq_tls_enable_slot(data,size,index,slot)&&hq_tls_attach(c);
}
int hq_plugin_mapped(CPU *c){return hq_plugin_module_mapped(c,0x01000000u);}
void hq_plugin_init_unlimiter(int full){
    void mw_unlimiter_init(int);mw_unlimiter_init(full&&!module_known_name("nfsmwunlimiter.asi"));
}
int hq_plugin_prepare_addons(CPU *c){
    uint32_t error=0;
    if(module_known_name("nfsmostwanted.xboxraindroplets.asi")){
        if(!module_load(c,"nfsmostwanted.xboxraindroplets.asi",&error))return 0;
        hq_capture(c,"raincrt",0x014067bfu);
        uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
        call_guest(c,0x01404380u,0,NULL);
        hq_capture(c,"rain",0x01404380u);
    }
    if(module_known_name("nfsmwunlimiter.asi")){
        if(!module_load(c,"nfsmwunlimiter.asi",&error))return 0;
        void mw_unlimiter_init(int);mw_unlimiter_init(0);
        hq_capture(c,"unlimiter",0x01814c74u);
    }
    if(module_known_name("nfsmwextraoptions.asi")){
        if(!module_load(c,"nfsmwextraoptions.asi",&error))return 0;
        hq_capture(c,"extraoptions",0x01c0fe6fu);
    }
    if(module_known_name("nfsmw_xenoneffects.asi")){
        if(!module_load(c,"nfsmw_xenoneffects.asi",&error))return 0;
        hq_capture(c,"xenoncrt",0x0240ab2eu);
    }
    return 1;
}
int hq_plugin_prepare(CPU *c,const char *config_path){
    char path[1024];
    if(!config_path){if(!fileio_resolve_game("scripts/X360Stuff.ini",path,sizeof path))return 0;config_path=path;}
    if(!hq_config_load(config_path,config)){fprintf(stderr,"ASI requires all 33 valid supplied config fields\n");return 0;}
    hq_capture_prepare();
    enabled=1;uint32_t error=0,handle=module_load(c,"x360stuff.asi",&error);
    if(!handle){enabled=0;fprintf(stderr,"ASI initialization refused: %u\n",error);return 0;}
    hq_capture(c,"crt",0x010071a2u);
    fprintf(stderr,"Experimental ASI CRT initialized; native config prepared\n");
    if(!hq_plugin_prepare_addons(c)){enabled=0;fprintf(stderr,"Addon initialization refused\n");return 0;}
    unsigned hq_dispatch_patch_count(void);fprintf(stderr,"HQ dispatch registrations: %u/128 after original module initialization\n",hq_dispatch_patch_count());return 1;
}
int hq_plugin_override(CPU *c,uint32_t address){
    if(!enabled||address!=0x01007e80u)return 0;
    memcpy(g_mem+0x0102b550u,config,sizeof config);hq_capture(c,"config",address);POP32(c->eip);
    fprintf(stderr,"ASI LoadConfig: applied 33 supplied fields\n");return 1;
}
void sub_01007e80(CPU *c){
    if(!hq_plugin_override(c,0x01007e80u))hq_plugin_route_error(c,0x01007e80u);
}
void hq_plugin_route_error(CPU *c,uint32_t address){
    hq_capture(c,"patch",address);
    fprintf(stderr,"Unknown native game patch at %08x caller=%08x; capture and compile this variant\n",address,MR32(c->esp));
    exit(78);
}
uint32_t hq_plugin_data_import(const char *name){
    uint32_t *slot=NULL;
    if(!strcmp(name,"?_Id_cnt@id@locale@std@@0HA"))slot=&id_count;
    if(!strcmp(name,"?id@?$codecvt@DDU_Mbstatet@@@std@@2V0locale@2@A"))slot=&codecvt_id;
    if(slot&&!*slot)*slot=gheap_alloc(1,4,1);
    if(slot&&!*slot){fprintf(stderr,"No memory for ASI data import\n");exit(78);}
    return slot?*slot:0;
}

/* Capture phase completion around the original AOT bodies. */
void sub_01007cb0_body(CPU *),sub_01013660_body(CPU *);
void sub_01007cb0(CPU *c){
    sub_01007cb0_body(c);
    if(!hq_audio_repair(ws_high_spec_audio()))hq_plugin_route_error(c,0x004c41deu);
    fprintf(stderr,"HQ audio selector: fallback %u Hz, high quality 48000 Hz\n",ws_high_spec_audio()?44100u:22050u);
    hq_capture(c,"init",0x01007cb0u);
}
void sub_01013660(CPU *c){sub_01013660_body(c);hq_capture(c,"render",0x01013660u);}

void sub_01007b10_body(CPU *),sub_01007b30_body(CPU *);
void sub_01007b10(CPU *c){hq_capture(c,"startup",0x01007b10u);sub_01007b10_body(c);}
void sub_01007b30(CPU *c){sub_01007b30_body(c);hq_capture(c,"late",0x01007b30u);}

/* These runtime writers patch other game functions before their next entry. */
void hq_plugin_checkpoint(CPU *c,unsigned point){
    hq_prepare_checkpoint(c,point);
    static unsigned seen;
    if(point<1||point>3)hq_plugin_route_error(c,point);
    int hq_checkpoint_known(unsigned);int known=hq_checkpoint_known(point);
    unsigned bit=1u<<point;
    if(!(seen&bit)||!known){
        static const char *names[]={"cartypes","racernames","eohotkeys"};
        static const uint32_t addresses[]={0x0180adcau,0x01809740u,0x01c04a50u};
        hq_capture(c,names[point-1],addresses[point-1]);
    }
    if(!known){fprintf(stderr,"Unknown runtime patch tuple at checkpoint %u; captured before game continuation\n",point);exit(78);}
    seen|=bit;
}
void sub_01809740_body(CPU *);
void sub_01809740(CPU *c){sub_01809740_body(c);hq_plugin_checkpoint(c,2);}

/* Called by the original delayed startup wrapper after its original game call. */
void sub_024030f0(CPU *c){
    char path[1024];uint8_t values[HQ_XENON_CONFIG_SIZE];uint64_t present;
    if(!fileio_resolve_game("scripts/NFSMW_XenonEffects.ini",path,sizeof path)||
       !hq_config_xenon_load(path,values,&present))hq_plugin_route_error(c,0x024030f0u);
    for(unsigned i=0;i<sizeof hq_xenon_fields/sizeof *hq_xenon_fields;i++){
        if(!(present&(1ull<<i)))continue;
        const HQField *field=&hq_xenon_fields[i];
        unsigned length=field->type=='s'?(unsigned)strlen((char*)values+field->offset)+1:field->type=='b'?1:4;
        memcpy(g_mem+HQ_XENON_CONFIG_BASE+field->offset,values+field->offset,length);
    }
    hq_capture(c,"xenonconfig",0x024030f0u);POP32(c->eip);
}

void sub_01c04a50_body(CPU *);
void sub_01c04a50(CPU *c){sub_01c04a50_body(c);hq_plugin_checkpoint(c,3);}
