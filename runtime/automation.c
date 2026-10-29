/* Repeatable guest input for menu/race verification. */
#include "kbd.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {uint64_t frame;unsigned scan,vk;int down,character;} Event;
static Event events[256];static unsigned count,next_event;
uint64_t g_mw_frame;
static FILE *commands;
static Event releases[32];

static int key(const char *name,unsigned *scan,unsigned *vk,int *character){
    static const struct {const char *name;unsigned scan,vk;} named[]={
        {"RETURN",0x1c,13},{"ESCAPE",1,27},{"UP",0xc8,38},{"DOWN",0xd0,40},
        {"LEFT",0xcb,37},{"RIGHT",0xcd,39},{"SPACE",0x39,32},{"BACKSPACE",0x0e,8}};
    for(unsigned i=0;i<sizeof named/sizeof *named;i++)if(!strcmp(name,named[i].name)){
        *scan=named[i].scan;*vk=named[i].vk;*character=named[i].vk==13?13:0;return 1;
    }
    static const unsigned letters[]={0x1e,0x30,0x2e,0x20,0x12,0x21,0x22,0x23,0x17,0x24,0x25,0x26,0x32,
        0x31,0x18,0x19,0x10,0x13,0x1f,0x14,0x16,0x2f,0x11,0x2d,0x15,0x2c};
    if(name[0]>='A'&&name[0]<='Z'&&!name[1]){
        *scan=letters[name[0]-'A'];*vk=(unsigned)name[0];*character=name[0];return 1;
    }
    return 0;
}

int automation_load(const char *path){
    count=next_event=0;
    if(!path||!*path)return 1;
    FILE *file=fopen(path,"r");if(!file)return 0;
    char line[128];Event parsed[256];unsigned n=0;int ok=1;
    while(fgets(line,sizeof line,file)){
        if(line[0]=='#'||line[0]=='\n')continue;
        char number[32],name[24],action[16],extra[2];
        if(n==256||sscanf(line,"%31s %23s %15s %1s",number,name,action,extra)!=3||number[0]=='-'){ok=0;break;}
        char *end;unsigned long long frame=strtoull(number,&end,10);
        Event e={.frame=frame,.down=!strcmp(action,"down")};
        if(*end||frame>10000000||(n&&frame<parsed[n-1].frame)||
           (!e.down&&strcmp(action,"up"))||!key(name,&e.scan,&e.vk,&e.character)){ok=0;break;}
        parsed[n++]=e;
    }
    if(ferror(file))ok=0;fclose(file);
    if(ok){memcpy(events,parsed,n*sizeof *events);count=n;}
    return ok;
}

int automation_open_commands(const char *path){
    if(commands)fclose(commands);commands=NULL;
    if(!path||!*path)return 1;
    commands=fopen(path,"r");return commands!=NULL;
}

static void send_key(const Event *e){
    kbd_set_key(KSRC_SCRIPT,e->scan,e->down);
    uint32_t lp=1u|((e->scan&0x7fu)<<16)|(e->scan&0x80u?1u<<24:0);
    kbd_post(e->down?0x100:0x101,e->vk,lp|(e->down?0:0xc0000000u));
    if(e->down&&e->character)kbd_post(0x102,(uint32_t)e->character,lp);
}

void automation_frame(uint64_t frame){
    g_mw_frame=frame;
    for(unsigned i=0;i<32;i++)if(releases[i].scan&&releases[i].frame<=frame){send_key(&releases[i]);releases[i].scan=0;}
    if(commands){
        char line[80];clearerr(commands);
        for(unsigned n=0;n<64&&fgets(line,sizeof line,commands);n++){
            if(!strcmp(line,"DUMP\n")){void metal_request_frame_dump(void);metal_request_frame_dump();continue;}
            if(!strcmp(line,"QUIT\n")){void lifecycle_request_quit(const char *);lifecycle_request_quit("automation");continue;}
            long blur;char trailing[2];
            if(sscanf(line,"BLUR %ld %1s",&blur,trailing)==1 && blur>0 && blur<=60000){
                void lifecycle_simulate_blur(long);lifecycle_simulate_blur(blur);continue;
            }
            double x,y;
            if(sscanf(line,"CLICK %lf %lf",&x,&y)==2&&x>=0&&x<=1&&y>=0&&y<=1){
                void metal_request_click(double,double);metal_request_click(x,y);continue;
            }
            char name[24],action[16],extra[2];Event e={0};
            if(sscanf(line,"%23s %15s %1s",name,action,extra)!=2||!key(name,&e.scan,&e.vk,&e.character))continue;
            e.down=!strcmp(action,"down")||!strcmp(action,"press");
            if(!e.down&&strcmp(action,"up"))continue;
            send_key(&e);
            if(!strcmp(action,"press"))for(unsigned i=0;i<32;i++)if(!releases[i].scan){
                e.down=0;e.frame=frame+4;releases[i]=e;break;
            }
            fprintf(stderr,"[automation] frame %llu: %s %s\n",(unsigned long long)frame,name,action);
        }
    }
    while(next_event<count&&events[next_event].frame<=frame){
        Event *e=&events[next_event++];
        send_key(e);
    }
}
