/* Supplied NFSMWFEShadows 2.1, SHA256 78cdf5df4ab50f5b29bd2b8a4f1a7050
 * 53675ba97fa14e2443f852bf2ad00a4b. The six enabled helpers match
 * AeroWidescreen/NFSMWFEShadows/NFSMWFEShadows/assembly.h.
 */
#include "cpu.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#define HOOK_SITE(a) a
#define HOOK_BRANCH(a,b) a

int fileio_resolve_game(const char *,char *,size_t);
void sub_007a1fa0(CPU *),sub_007a2200(CPU *);
static int active,world,disable_car_receivers;

int mw_fe_shadows_init(int enabled){
    active=0;world=0;disable_car_receivers=0;if(!enabled)return 1;
    static const char *keys[]={"RenderWorldShadows","RenderCarShadows","DisableShadowsOnCars","RestoreShadows"};
    int values[]={1,1,1,0},valid=1;
    char path[4096],line[512],section[64]="";
    if(!fileio_resolve_game("scripts/NFSMWFEShadows.ini",path,sizeof path))return 0;
    FILE *file=fopen(path,"r");if(!file&&errno!=ENOENT)return 0;
    while(file&&fgets(line,sizeof line,file)){
        if(!strchr(line,'\n')&&!feof(file)){valid=0;break;}
        char *comment=strstr(line,"//");if(comment)*comment=0;
        comment=strchr(line,';');if(comment)*comment=0;
        char *p=line;while(isspace((unsigned char)*p))p++;
        if(*p=='['){section[0]=0;sscanf(p,"[%63[^]]]",section);continue;}
        if(strcasecmp(section,"MAIN"))continue;
        char *value=strchr(p,'=');if(!value)continue;*value++=0;
        size_t n=strlen(p);while(n&&isspace((unsigned char)p[n-1]))p[--n]=0;
        int key=0;while(key<4&&strcasecmp(p,keys[key]))key++;if(key==4)continue;
        errno=0;char *end;long number=strtol(value,&end,10);int parsed=end!=value;
        while(isspace((unsigned char)*end))end++;
        if(!parsed||*end||errno||(number!=0&&number!=1)){valid=0;break;}
        values[key]=(int)number;
    }
    if(file){if(ferror(file))valid=0;fclose(file);}
    /* The supplied configuration disables these two unported features. */
    if(!valid||values[1]||values[3])return 0;
    world=values[0];disable_car_receivers=values[2];active=1;return 1;
}

static int frontend(CPU *c){
    uint32_t value=MR8(0x00925e90),result=value-3;FLAGS_SUB(value,3u,result,8);
    return value==3;
}
static int shadows(CPU *c){
    uint32_t value=MR8(0x00901830);FLAGS_SUB(value,0u,value,8);
    return (int8_t)value>0;
}
static uint32_t view_type(void){
    uint32_t view=MR32(0x00982a20),index=MR32(view+4);
    return MR32(0x009195e4+index*0x70u);
}

int mw_fe_shadows_branch(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_BRANCH(0x0074e37f,0x0074e386): {
        if(!active)return 0;
        uint32_t view=view_type(),result=view-1;FLAGS_SUB(view,1u,result,32);
        if(view!=1){
            uint32_t flow=MR32(0x00925e90);result=flow-3;FLAGS_SUB(flow,3u,result,32);
            if(flow==3)c->ecx&=0xffffff00u;
        }
        /* The actual ASI writes +DC, replacing the game's +D8 store. */
        MR32(c->esp+0xdc)=c->eax;return 1;
    }
    case HOOK_BRANCH(0x007a22f2,0x007a22f8): {
        if(!active)return 0;
        uint32_t view=view_type(),result=view-1;FLAGS_SUB(view,1u,result,32);
        /* The existing target is RET4, after the caller's POP EBX. */
        return view!=1;
    }
    case HOOK_BRANCH(0x006e0b6e,0x006e0bed):
        if(!active||!frontend(c)||!shadows(c))return 0;
        c->eax=(uint32_t)(int32_t)(int8_t)c->edx;
        MR32(c->esi+0x38)=c->eax;
        c->ebx=c->eax^MR32(c->esi+0xc);FLAGS_LOG(c->ebx,32);
        c->edx=MR32(0x00982a20);MR32(c->esi+0x38)=c->ebx;
        c->ebx=MR8(MR32(MR32(c->ebp+0x18))+0x51);
        MR8(c->esi+0x3b)=(uint8_t)c->ebx;return 1;
    default:return -1;
    }
}

int mw_fe_shadows_hook(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_SITE(0x006e518b):
        /* The pinned X360 replacement already rendered the frontend world. */
        if(active&&MR8(0x006e5186)==0xe8&&0x006e518bu+MR32(0x006e5187)==0x0100bdb0u)return 1;
        /* Original 723FA0 already ran and consumed its two arguments.
         * These native guest calls retain the ASI's register/stack effects. */
        if(active&&frontend(c)&&shadows(c)){
            PUSH32(0x006e518bu);sub_007a1fa0(c);
            uint32_t value=c->eax;FLAGS_SUB(value,0u,value,32);
            if(value){
                FLAGS_SUB((uint32_t)world,0u,(uint32_t)world,8);
                if(world){PUSH32(4u);c->ecx=c->eax;PUSH32(0x006e518bu);sub_007a2200(c);}
                FLAGS_SUB(0u,0u,0u,8); /* RenderCarShadows is disabled. */
            }
        }
        return 1;
    case HOOK_SITE(0x006c8323):
        if(active&&disable_car_receivers&&frontend(c)&&shadows(c)){
            uint32_t view=MR8(MR32(0x00982c80)+4),result=view-4;FLAGS_SUB(view,4u,result,8);
            if(view==4)MR32(c->esp+0x54)=0xffc00000u;
        }
        return 1;
    case HOOK_SITE(0x006e551b):
        if(active&&frontend(c)){
            FPUSH((double)(int32_t)MR32(0x0093db3c));
            double input=ST(0);ST(0)=X87R2(input,2048.0,input/2048.0);
            float resolution=(float)ST(0);FPOP();FPUSH(resolution);
            input=ST(0);ST(0)=X87R2(input,2.0,input*2.0);
            float bias=(float)ST(0);FPOP();uint32_t bits;memcpy(&bits,&bias,4);
            uint32_t result=bits-0x40000000u;FLAGS_SUB(bits,0x40000000u,result,32);
            if((int32_t)bits<(int32_t)0x40000000u)MR32(c->esp+8)=0x40000000u;
            else {c->eax=bits;MR32(c->esp+8)=bits;}
        }
        return 1;
    default:return 0;
    }
}
