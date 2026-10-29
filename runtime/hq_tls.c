#include "cpu.h"
#include "hq_tls.h"
uint32_t gheap_alloc(int,uint32_t,int);
void gheap_free(int,uint32_t);
static struct { uint32_t data,size; } templates[HQ_STATIC_TLS_COUNT];

int hq_tls_enable_slot(uint32_t data,uint32_t size,uint32_t index,uint32_t slot){
    if(slot<HQ_STATIC_TLS_SLOT||slot-HQ_STATIC_TLS_SLOT>=HQ_STATIC_TLS_COUNT||!size||size>4096
            ||!mem_is_committed(data)||!mem_is_committed(data+size-1)
            ||!mem_is_committed(index+3))return 0;
    templates[slot-HQ_STATIC_TLS_SLOT].data=data;
    templates[slot-HQ_STATIC_TLS_SLOT].size=size;
    MR32(index)=slot;return 1;
}
int hq_tls_enable(uint32_t data,uint32_t size,uint32_t index){
    return hq_tls_enable_slot(data,size,index,HQ_STATIC_TLS_SLOT);
}
int hq_tls_attach(CPU *c){
    for(unsigned i=0;i<HQ_STATIC_TLS_COUNT;i++){
        if(!templates[i].size)continue;
        if(!c||!c->fs_base||!mem_is_committed(c->fs_base+0x2f))return 0;
        uint32_t slots=MR32(c->fs_base+0x2c),slot=slots+(HQ_STATIC_TLS_SLOT+i)*4;
        if(!slots||!mem_is_committed(slot+3))return 0;
        if(MR32(slot))continue;
        uint32_t data=gheap_alloc(1,templates[i].size,1);
        if(!data)return 0;
        memcpy(g_mem+data,g_mem+templates[i].data,templates[i].size);MR32(slot)=data;
    }
    return 1;
}
void hq_tls_detach(CPU *c){
    if(!c||!c->fs_base)return;
    uint32_t slots=MR32(c->fs_base+0x2c);if(!slots)return;
    for(unsigned i=0;i<HQ_STATIC_TLS_COUNT;i++){
        if(!templates[i].size)continue;
        uint32_t slot=slots+(HQ_STATIC_TLS_SLOT+i)*4,data=MR32(slot);
        if(data){MR32(slot)=0;gheap_free(1,data);}
    }
}
