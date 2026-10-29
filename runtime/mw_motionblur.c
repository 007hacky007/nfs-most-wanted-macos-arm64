/* MotionBlurController 1.0.0.100: four scale operands and minimum speed.
 * The pinned ASI redirects each original 1.1 multiplication to its configured
 * float. Paired instruction hooks retain the input and replace only that result.
 * Behavior reference: nlgxzef/NFSMWMotionBlurController; supplied binary verified.
 */
#include "cpu.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#define HOOK_SITE(a) a

int fileio_resolve_game(const char *,char *,size_t);
static int active;
static float amount,original_minimum;
static _Thread_local struct {CPU *cpu;uint32_t end,stack;int top;double input;} operand;

int mw_motionblur_init(int enabled){
    if(active)MRF32(0x008f9b10u)=original_minimum;
    active=0;memset(&operand,0,sizeof operand);
    if(!enabled)return 1;
    float scale=.25f,minimum=1.f;
    char path[4096],line[512],section[64]="";
    if(!fileio_resolve_game("scripts/NFSMWMotionBlurControllerSettings.ini",path,sizeof path))return 0;
    FILE *file=fopen(path,"r");
    if(!file&&errno!=ENOENT)return 0;
    int valid=1;
    while(file&&fgets(line,sizeof line,file)){
        if(!strchr(line,'\n')&&!feof(file)){valid=0;break;}
        char *comment=strstr(line,"//");if(comment)*comment=0;
        comment=strchr(line,';');if(comment)*comment=0;
        char *p=line;while(isspace((unsigned char)*p))p++;
        if(*p=='['){sscanf(p,"[%63[^]]]",section);continue;}
        if(strcasecmp(section,"Main"))continue;
        char *equals=strchr(p,'=');if(!equals)continue;
        *equals=0;char *text=equals+1;
        size_t n=strlen(p);while(n&&isspace((unsigned char)p[n-1]))p[--n]=0;
        float *value=!strcasecmp(p,"MotionBlurAmount")?&scale:
                     !strcasecmp(p,"MotionBlurMinEffectiveSpeed")?&minimum:NULL;
        if(!value)continue;
        char *end;errno=0;float parsed=strtof(text,&end);int number=end!=text;
        while(isspace((unsigned char)*end))end++;
        if(!number||*end||errno||!isfinite(parsed)){valid=0;break;}
        *value=parsed;
    }
    if(file){if(ferror(file))valid=0;fclose(file);}
    if(!valid)return 0;
    amount=scale;original_minimum=MRF32(0x008f9b10u);
    MRF32(0x008f9b10u)=minimum;active=1;
    fprintf(stderr,"Native motion blur: amount %.3f, minimum speed %.3f\n",amount,minimum);
    return 1;
}

int mw_motionblur_hook(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_SITE(0x006dbd44):case HOOK_SITE(0x006dbd54):
    case HOOK_SITE(0x006dbd64):case HOOK_SITE(0x006dbd72):
        if(active){operand.cpu=c;operand.end=ip+6;operand.stack=c->esp;
            operand.top=c->top;operand.input=c->st[c->top&7];}
        return 1;
    case HOOK_SITE(0x006dbd4a):case HOOK_SITE(0x006dbd5a):
    case HOOK_SITE(0x006dbd6a):case HOOK_SITE(0x006dbd78):
        if(active&&operand.cpu==c&&operand.end==ip&&operand.stack==c->esp&&operand.top==c->top){
            double input=operand.input,factor=(double)amount;
            c->st[c->top&7]=X87R2(input,factor,input*factor);
            operand.cpu=NULL;
        }
        return 1;
    default:return 0;
    }
}
