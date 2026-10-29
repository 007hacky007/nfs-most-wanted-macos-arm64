/* Native behavior verified against the supplied HD Reflections 2.0 binary.
 * Reference: AeroWidescreen/NFSHDReflections, SOURCE/NFSMW. */
#include "cpu.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#define HOOK_SITE(a) a
#define HOOK_BRANCH(a,b) a
int fileio_resolve_game(const char *,char *,size_t);
int ws_get_resolution(unsigned *,unsigned *);
uint32_t gheap_alloc(int,uint32_t,int);
enum {AUTO,CSCALE,MSCALE,RSCALE,OLDGPU,FE,CUBE,MX,MY,RX,RY,BRIGHTFIX,LOD,FORCEMIRROR,
      CULL,VT,SHADERS,DETAILS,CARS,WATER,SHADOWS,LASTGEN,DISTANCE,BRIGHTNESS,POOLS,NOCULL,OPTIONS};
static const struct {const char *section,*key;double initial;int real;} keys[OPTIONS]={
    {"RESOLUTION","AutoRes",1,0},{"RESOLUTION","CubemapScale",1,1},
    {"RESOLUTION","MirrorScale",1,1},{"RESOLUTION","RoadScale",1,1},
    {"RESOLUTION","OldGPUCompatibility",0,0},{"RESOLUTION","FECubemapRes",256,0},
    {"CUSTOM RESOLUTION","CubemapRes",256,0},{"CUSTOM RESOLUTION","MirrorResX",256,0},
    {"CUSTOM RESOLUTION","MirrorResY",256,0},{"CUSTOM RESOLUTION","RoadResX",320,0},
    {"CUSTOM RESOLUTION","RoadResY",240,0},{"GENERAL","CubemapBrightnessFix",1,0},
    {"GENERAL","ImproveReflectionLOD",1,0},{"GENERAL","ForceEnableMirror",1,0},
    {"GENERAL","RestoreBackfaceCulling",1,0},{"GENERAL","RestoreVisualTreatment",1,0},
    {"GENERAL","RestoreShaders",1,0},{"GENERAL","RestoreDetails",1,0},
    {"GENERAL","RestoreCars",0,0},{"GENERAL","RestoreWaterReflections",0,0},
    {"GENERAL","RestoreShadows",1,0},{"GENERAL","RemoveLastGenEffects",2,0},
    {"GENERAL","OptimizeRenderDistance",1,0},{"GENERAL","VehicleReflectionBrightness",1,1},
    {"EXTRA","ExpandMemoryPools",1,0},{"EXTRA","DisableBackFaceCulling",0,0}
};
static double values[OPTIONS];
static int active;
static unsigned cube,road_x,road_y,mirror_x,mirror_y;
static uint32_t sunflare;

static int read_config(double *out){
    char path[4096],line[512],section[64]="";
    if(!fileio_resolve_game("scripts/NFSMWHDReflections.ini",path,sizeof path))return 0;
    FILE *file=fopen(path,"r");if(!file)return 0;int valid=1;
    while(fgets(line,sizeof line,file)){
        if(!strchr(line,'\n')&&!feof(file)){valid=0;break;}
        char *comment=strchr(line,';');if(comment)*comment=0;
        comment=strstr(line,"//");if(comment)*comment=0;
        char *p=line;while(isspace((unsigned char)*p))p++;
        if(*p=='['){section[0]=0;sscanf(p,"[%63[^]]]",section);continue;}
        char *value=strchr(p,'=');if(!value)continue;*value++=0;
        size_t length=strlen(p);while(length&&isspace((unsigned char)p[length-1]))p[--length]=0;
        unsigned key=0;while(key<OPTIONS&&(strcasecmp(section,keys[key].section)||strcasecmp(p,keys[key].key)))key++;
        if(key==OPTIONS)continue;
        errno=0;char *end;double number=keys[key].real?strtod(value,&end):(double)strtol(value,&end,10);
        int present=end!=value;while(isspace((unsigned char)*end))end++;
        if(!present||*end||errno||!isfinite(number)){valid=0;break;}
        out[key]=keys[key].real?(double)(float)number:number;
        if(!isfinite(out[key])){valid=0;break;}
    }
    if(ferror(file))valid=0;fclose(file);return valid;
}
static int sizes(void){
    unsigned width=0,height=0;
    if(values[AUTO]&&!ws_get_resolution(&width,&height))return 0;
    unsigned base[5]={(unsigned)values[CUBE],(unsigned)values[MX],(unsigned)values[MY],(unsigned)values[RX],(unsigned)values[RY]};
    if(values[AUTO]){base[0]=height;base[1]=width/2;base[2]=height/6;base[3]=width;base[4]=height;}
    unsigned result[5];
    for(unsigned i=0;i<5;i++){
        float scaled=(float)base[i]*(float)values[i?i<3?MSCALE:RSCALE:CSCALE];
        if(!isfinite(scaled)||scaled<1||scaled>8192)return 0;result[i]=(unsigned)scaled;
    }
    cube=result[0];if(values[OLDGPU]){unsigned power=1;while(power<=cube/2)power*=2;cube=power;}
    mirror_x=result[1];mirror_y=result[2];road_x=result[3];road_y=result[4];return 1;
}
static void publish_sizes(void){MR32(0x008f9008)=mirror_x;MR32(0x008f900c)=mirror_y;}
int mw_hdreflections_init(int enabled){
    active=0;if(!enabled)return 1;
    double config[OPTIONS];for(unsigned i=0;i<OPTIONS;i++)config[i]=keys[i].initial;
    if(!read_config(config))return 0;
    for(unsigned i=0;i<OPTIONS;i++){
        if(i==CSCALE||i==MSCALE||i==RSCALE){if(config[i]<=0)return 0;continue;}
        if(i==FE||i==CUBE||i==MX||i==MY||i==RX||i==RY){if(config[i]<1||config[i]>8192)return 0;continue;}
        if(i==BRIGHTNESS)continue;
        if(config[i]<0||config[i]>(i==LASTGEN?2:1))return 0;
    }
    if(config[FORCEMIRROR]||config[VT]||config[SHADERS]||config[CARS]||config[SHADOWS]||config[BRIGHTNESS]!=1)return 0;
    memcpy(values,config,sizeof values);
    int ready=sizes();unsigned width,height;
    if(!ready&&(!values[AUTO]||ws_get_resolution(&width,&height)))return 0;
    if(values[DETAILS]&&!sunflare){sunflare=gheap_alloc(1,200,1);if(!sunflare)return 0;}
    active=1;if(ready)publish_sizes();
    if(values[POOLS]){MR32(0x008f5790)=0x000be6e0;MR32(0x008f7ef0)=0x0001cc00;}
    if(values[NOCULL])MR8(0x008fae44)=0;
    return 1;
}
static _Thread_local CPU *traffic_cpu;
static void invoke(CPU *c,uint32_t function,uint32_t ret){PUSH32(ret);dispatch_indirect(c,function);}
static void add_stack(CPU *c,uint32_t bytes){uint32_t a=c->esp,result=a+bytes;FLAGS_ADD(a,bytes,result,32);c->esp=result;}
static void release_queries(CPU *c,uint32_t ret){
    c->esi=sunflare+0x24;c->edi=c->esi+0x10;
    while(c->esi<c->edi){
        c->eax=MR32(c->esi);c->edx=c->eax?MR32(c->eax):0;
        FLAGS_LOG(c->eax,32);
        if(c->eax){PUSH32(c->eax);invoke(c,MR32(c->edx+8),ret);MR32(c->esi)=0;}
        uint32_t a=c->esi,result=a+4;FLAGS_ADD(a,4u,result,32);c->esi=result;
        result=c->esi-c->edi;FLAGS_SUB(c->esi,c->edi,result,32);
    }
    c->edi=0x0093e04c;
}
static void compare(CPU *c,uint32_t a,uint32_t b){uint32_t result=a-b;FLAGS_SUB(a,b,result,32);}
int mw_hdreflections_hook(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_SITE(0x006bcdfa):case HOOK_SITE(0x006bce34):
        if(active&&sizes()){publish_sizes();MR32(c->esp)=road_x;MR32(c->esp+4)=road_y;}return 1;
    case HOOK_SITE(0x006bd547):
        if(active&&sizes()){publish_sizes();MR32(c->esp)=cube;}return 1;
    case HOOK_SITE(0x006bd591):
        if(active&&sizes()){publish_sizes();MR32(c->esp)=MR32(c->esp+4)=cube;}return 1;
    case HOOK_SITE(0x006bd34a):if(active&&sizes()){publish_sizes();c->edx=cube;}return 1;
    case HOOK_SITE(0x006bd502):if(active)c->ecx=(uint32_t)values[FE];return 1;
    case HOOK_SITE(0x006cfc31):
        if(active&&sizes()){publish_sizes();MR32(c->ecx+0x14)=road_x;MR32(c->ecx+0x18)=road_y;}return 1;
    case HOOK_SITE(0x006bcfb7):case HOOK_SITE(0x006bcffa):case HOOK_SITE(0x006bd19f):
        if(active&&sizes()){publish_sizes();}return 1;
    case HOOK_SITE(0x006bfe5c):case HOOK_SITE(0x006bfec1):
        if(active&&values[LOD]&&MR32(c->esp)==0x1000)MR32(c->esp)=0x6002;return 1;
    case HOOK_SITE(0x006bff24):if(active&&values[LOD])MR32(c->esp)=0x600;return 1;
    case HOOK_SITE(0x005f7399):case HOOK_SITE(0x005f73b5):
        if(active&&values[POOLS])MR32(c->esp)=0x2c8000;return 1;
    case HOOK_SITE(0x00665fdf):if(active&&values[POOLS])MR32(c->esp)=0x8000;return 1;
    case HOOK_SITE(0x005009d6):case HOOK_SITE(0x005009e0):
        if(active&&values[POOLS])MR32(c->esp)=2048000;return 1;
    case HOOK_SITE(0x00500a16):if(active&&values[POOLS])MR32(0x00915f7c)=2048000;return 1;
    case HOOK_SITE(0x00507781):
        if(traffic_cpu==c&&MR32(c->esp+16)==0x006de9f0)c->eax=2;return 1;
    case HOOK_SITE(0x006db265):case HOOK_SITE(0x006e6db2):
        if(active&&values[DETAILS]){c->ecx=sunflare;invoke(c,0x006c00d0,ip);}return 1;
    case HOOK_SITE(0x006db0fe):if(active&&values[DETAILS])release_queries(c,ip);return 1;
    case HOOK_SITE(0x006de81e):if(active&&values[DETAILS])MR32(c->esp)=0;return 1;
    case HOOK_SITE(0x006def3d):if(active&&values[CULL])MR32(0x008fae6c)=3;return 1;
    case HOOK_SITE(0x006def42):if(active&&values[CULL])MR32(0x008fae6c)=2;return 1;
    case HOOK_SITE(0x006e73ab):
        if(active&&values[DISTANCE]){
            uint32_t view=MR32(c->esi+4);compare(c,view,3);
            if(view==3)MR32(c->esp)=0x43c00000;
            else{compare(c,view,20);if(view==20)MR32(c->esp)=0x43c00000;
                else{compare(c,view,18);int cube_view=(int32_t)view>=18;compare(c,view,3);if(cube_view)MR32(c->esp)=0x42c80000;}}
        }return 1;
    case HOOK_SITE(0x006db5c4):
        if(active&&values[DISTANCE]){
            uint32_t view=MR32(MR32(0x00982a20)+4);c->eax=MR32(0x009195e4+view*0x70);
            compare(c,c->eax,18);
            if((int32_t)c->eax>=18)ST(0)=.5;
            else{compare(c,c->eax,3);ST(0)=c->eax==3?.5:(double)MRF32(0x008f935c);}
        }return 1;
    default:return 0;
    }
}
int mw_hdreflections_branch(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_BRANCH(0x006bfe3d,0x006bfe57):
        if(!active||!values[LOD])return 0;
        compare(c,c->esi,0x00919730);if(c->esi!=0x00919730){c->ecx=0x00982af4;FLAGS_LOG(c->ecx,32);}return 1;
    case HOOK_BRANCH(0x007293d9,0x007293dc):
        if(!active||!values[LOD])return 0;
        {uint32_t result=(c->eax>>8)&6u;FLAGS_LOG(result,8);}return 1;
    case HOOK_BRANCH(0x004fae9a,0x004faea2):case HOOK_BRANCH(0x004faeb0,0x004faeb5):return active&&values[LOD];
    case HOOK_BRANCH(0x00500a00,0x00500a05):
        if(!active||!values[POOLS])return 0;
        {uint32_t a=c->eax,result=a+2048000u;FLAGS_ADD(a,2048000u,result,32);c->eax=result;}return 1;
    case HOOK_BRANCH(0x006de9f0,0x006de9f8):
        if(!active||!values[DETAILS])return 0;
        {CPU *previous=traffic_cpu;traffic_cpu=c;invoke(c,0x00507770,ip);traffic_cpu=previous;}
        PUSH32(0x00919730);invoke(c,0x00505e80,ip);add_stack(c,12);return 1;
    case HOOK_BRANCH(0x006de96d,0x006de990):
        if(!active||!values[DETAILS])return 0;
        PUSH32(1);PUSH32(0x00919730);c->ecx=c->esp+0xe8;invoke(c,0x00723fa0,ip);
        invoke(c,0x006e2f50,ip);
        {uint32_t a=(uint32_t)values[LOD],result=a-1u;FLAGS_SUB(a,1u,result,8);}
        if(values[LOD]){PUSH32(0);PUSH32(0x00919730);invoke(c,0x007538d0,ip);add_stack(c,8);}
        PUSH32(c->ebx);PUSH32(0x00919730);invoke(c,0x00750b10,ip);invoke(c,0x006e2f50,ip);
        PUSH32(0x00919730);c->ecx=sunflare;invoke(c,0x006d04e0,ip);return 1;
    case HOOK_BRANCH(0x00729479,0x00729486):return active&&values[DETAILS];
    case HOOK_BRANCH(0x0074e816,0x0074e818):
        if(!active||!values[DETAILS])return 0;
        {uint32_t view=MR32(c->edi+4);compare(c,view,1);if(view==1)return 1;compare(c,view,3);return view==3;}
    case HOOK_BRANCH(0x006bfef7,0x006bfef9):case HOOK_BRANCH(0x006de508,0x006de50a):return active&&values[WATER];
    case HOOK_BRANCH(0x00504c56,0x00504c5b):return active&&values[LASTGEN]>=1;
    case HOOK_BRANCH(0x00738207,0x0073820c):return active&&values[LASTGEN]>=2;
    case HOOK_BRANCH(0x006db5ab,0x006db5b1):return active&&values[DISTANCE];
    default:return -1;
    }
}
