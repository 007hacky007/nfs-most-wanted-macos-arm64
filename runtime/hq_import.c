#include "hq_import.h"
#include "module.h"
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
uint32_t gheap_alloc(int,uint32_t,int);
void gheap_free(int,uint32_t);
int hq_import_forward(CPU *c,const char *dll,const char *name){
    if(strcasecmp(dll,"d3dx9_43.dll"))return 0;
    static const char *supported[]={"D3DXCreateEffectPool","D3DXVec4Transform",
        "D3DXLoadVolumeFromMemory","D3DXCreateEffect","D3DXMatrixMultiply","D3DXSaveSurfaceToFileA","D3DXCreateTextureFromFileInMemory"};
    static uint32_t cache[7];int known=-1;
    for(unsigned i=0;i<sizeof supported/sizeof *supported;i++)if(!strcmp(name,supported[i]))known=(int)i;
    if(known<0){fprintf(stderr,"Unverified D3DX43 alias: %s\n",name);exit(78);}
    CPU save=*c;uint32_t error=0,h=module_by_name("d3dx9_26.dll");
    if(!h)h=module_load(c,"d3dx9_26.dll",&error);
    *c=save;
    uint32_t fn=cache[known],nm=fn?0:gheap_alloc(1,(uint32_t)strlen(name)+1,0);
    if(h&&nm){memcpy(g_mem+nm,name,strlen(name)+1);fn=module_proc(h,nm,&error);}
    if(nm)gheap_free(1,nm);
    if(!h)fn=0;
    cache[known]=fn;
    if(!fn){fprintf(stderr,"D3DX43 alias failed: %s error %u\n",name,error);exit(78);}
    dispatch_indirect(c,fn);return 1;
}
