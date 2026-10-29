#include "cpu.h"
#include <stdio.h>
int ws_get_resolution(unsigned *,unsigned *);
void sub_01016f10_body(CPU *);
/* The game's video-mode table remains logical after the device-size override. */
void hq_video_resolution(uint32_t width,uint32_t height){
    unsigned w,h;
    if(!ws_get_resolution(&w,&h))return;
    if(!mem_is_committed(width+3)||!mem_is_committed(height+3))return;
    MR32(width)=w;MR32(height)=h;
    static int reported;
    if(!reported++){fprintf(stderr,"HQ GSYSTEM resolution: physical %ux%u\n",w,h);}
}
void sub_01016f10(CPU *c){
    uint32_t width=c->ecx,height=c->edx;
    sub_01016f10_body(c);
    hq_video_resolution(width,height);
}
