#include "hq_native.h"
void hq_native_resolve(const void *pc,uintptr_t *best,uint32_t *guest,const char **name){
    uintptr_t address=(uintptr_t)pc;
    for(unsigned i=0;i<g_hq_native_count;i++){
        uintptr_t function=(uintptr_t)g_hq_native[i].function;
        if(function<=address&&function>*best){*best=function;*guest=g_hq_native[i].guest;if(name)*name=g_hq_native[i].name;}
    }
}
