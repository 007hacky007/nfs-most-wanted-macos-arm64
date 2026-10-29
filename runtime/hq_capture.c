#include "hq_capture.h"
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
static unsigned sequence;
const char *hq_capture_path(const char *name){
    static char path[4096];const char *directory=getenv("NFSMW_HQ_CAPTURE_DIR");
    if(!directory||!*directory)directory="out";
    int n=snprintf(path,sizeof path,"%s/%s",directory,name);
    if(n<0||(size_t)n>=sizeof path){fprintf(stderr,"HQ capture path too long\n");exit(78);}return path;
}
static int write_data(const char *name,const void *data,size_t size){
    FILE *file=fopen(hq_capture_path(name),"wb");if(!file)return 0;
    int ok=fwrite(data,1,size,file)==size;if(fclose(file))ok=0;return ok;
}
static int write_image(const char *name,uint32_t base,uint32_t size){
    FILE *file=fopen(hq_capture_path(name),"wb");if(!file)return 0;
    static const uint8_t zero[0x4000]={0};int ok=1;
    for(uint32_t offset=0;offset<size;){
        uint32_t n=0x4000-((base+offset)&0x3fff);if(n>size-offset)n=size-offset;
        const uint8_t *data=mem_is_committed(base+offset)?g_mem+base+offset:zero;
        if(fwrite(data,1,n,file)!=n){ok=0;break;}offset+=n;
    }
    if(fclose(file))ok=0;return ok;
}
void hq_capture(CPU *c,const char *reason,uint32_t address){
    const char *directory=getenv("NFSMW_HQ_CAPTURE_DIR");if(!directory||!*directory||!c)return;
    for(const char *p=reason;*p;p++)if(!(*p>='a'&&*p<='z'))return;
    unsigned id=++sequence;char name[128];int ok;
    snprintf(name,sizeof name,"%04u-%s.game.bin",id,reason);ok=write_image(name,MW_BASE,MW_IMAGE_SIZE);
    snprintf(name,sizeof name,"%04u-%s.asi.bin",id,reason);ok&=write_image(name,0x01000000u,0x36000u);
    if(mem_is_committed(0x01400000u)){
        snprintf(name,sizeof name,"%04u-%s.rain.bin",id,reason);ok&=write_image(name,0x01400000u,0x34000u);
    }
    if(mem_is_committed(0x01800000u)){
        snprintf(name,sizeof name,"%04u-%s.unlimiter.bin",id,reason);ok&=write_image(name,0x01800000u,0x4d000u);
    }
    if(mem_is_committed(0x01c00000u)){
        snprintf(name,sizeof name,"%04u-%s.extraoptions.bin",id,reason);ok&=write_image(name,0x01c00000u,0x48000u);
    }
    if(mem_is_committed(0x02400000u)){
        snprintf(name,sizeof name,"%04u-%s.xenon.bin",id,reason);ok&=write_image(name,0x02400000u,0x16000u);
    }
    uint32_t car_count=0,car_table=0;
    if(!strcmp(reason,"cartypes")){
        if(mem_is_committed(0x009b09dbu)&&mem_is_committed(0x01847817u)){
            car_table=MR32(0x009b09d8u);car_count=MR32(0x01847814u);
        }
        uint32_t bytes=car_count*208u;
        int valid=car_count&&car_count<=4096u&&car_table&&car_table<=UINT32_MAX-bytes;
        if(valid)for(uint64_t address=car_table;address<(uint64_t)car_table+bytes;address=(address|0x3fffu)+1)
            if(!mem_is_committed((uint32_t)address)){valid=0;break;}
        if(valid){snprintf(name,sizeof name,"%04u-%s.car-types.bin",id,reason);ok&=write_image(name,car_table,bytes);}
        else ok=0;
    }
    snprintf(name,sizeof name,"%04u-%s.cpu.bin",id,reason);ok&=write_data(name,c,sizeof *c);
    snprintf(name,sizeof name,"%04u-%s.json",id,reason);FILE *file=fopen(hq_capture_path(name),"w");
    if(file){
        uint32_t top=mem_is_committed(c->esp+3)?MR32(c->esp):0;
        uint32_t ret=(!strcmp(reason,"import")||!strcmp(reason,"init")||!strcmp(reason,"render"))?c->eip:top;
        fprintf(file,"{\"reason\":\"%s\",\"address\":%u,\"return_address\":%u,\"stack_top\":%u,\"game_base\":%u,\"game_size\":%u,\"asi_base\":16777216,\"asi_size\":221184,\"cpu_size\":%zu,\"eip\":%u,\"esp\":%u,\"eax\":%u,\"ecx\":%u,\"top\":%u,\"car_type_count\":%u,\"car_type_table\":%u,\"complete\":%s}\n",
            reason,address,ret,top,MW_BASE,MW_IMAGE_SIZE,sizeof *c,c->eip,c->esp,c->eax,c->ecx,c->top,car_count,car_table,ok?"true":"false");
        if(fclose(file))ok=0;
    }else ok=0;
    fprintf(stderr,"HQ_CAPTURE %04u %s at %08x: %s\n",id,reason,address,ok?"written":"incomplete");
}

/* Paths are prepared before guest execution. The signal path uses only
 * open/write/close and direct memory reads; no stdio allocation or locks. */
static char fault_paths[8][4096];
void hq_capture_prepare(void){
    const char *directory=getenv("NFSMW_HQ_CAPTURE_DIR");if(!directory||!*directory)return;
    const char *suffix[]={"game.bin","asi.bin","cpu.bin","json","rain.bin","unlimiter.bin","extraoptions.bin","xenon.bin"};
    for(unsigned i=0;i<8;i++){
        int n=snprintf(fault_paths[i],sizeof fault_paths[i],"%s/fault.%s",directory,suffix[i]);
        if(n<0||(size_t)n>=sizeof fault_paths[i]){fault_paths[0][0]=0;return;}
    }
}
static int signal_write(int fd,const void *bytes,size_t size){
    const uint8_t *data=bytes;
    while(size){ssize_t n=write(fd,data,size);if(n<0&&errno==EINTR)continue;if(n<=0)return 0;data+=n;size-=(size_t)n;}return 1;
}
static int signal_image(const char *path,uint32_t base,uint32_t size){
    int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC,0600);if(fd<0)return 0;
    static const uint8_t zero[0x4000]={0};int ok=1;
    for(uint32_t offset=0;offset<size;){
        uint32_t n=0x4000-((base+offset)&0x3fff);if(n>size-offset)n=size-offset;
        if(!signal_write(fd,mem_is_committed(base+offset)?g_mem+base+offset:zero,n)){ok=0;break;}offset+=n;
    }close(fd);return ok;
}
static char *signal_text(char *out,const char *text){while(*text)*out++=*text++;return out;}
static char *signal_uint(char *out,uint32_t value){
    char digits[10];unsigned n=0;do{digits[n++]=(char)('0'+value%10);value/=10;}while(value);
    while(n)*out++=digits[--n];return out;
}
void hq_capture_fault(const CPU *c,uint32_t address,uint32_t guest,const char *name){
    if(!fault_paths[0][0]||!c)return;
    int ok=signal_image(fault_paths[0],MW_BASE,MW_IMAGE_SIZE);
    ok&=signal_image(fault_paths[1],0x01000000u,0x36000u);
    static const uint32_t bases[]={0x01400000u,0x01800000u,0x01c00000u,0x02400000u};
    static const uint32_t sizes[]={0x34000u,0x4d000u,0x48000u,0x16000u};
    for(unsigned i=0;i<4;i++)if(mem_is_committed(bases[i]))ok&=signal_image(fault_paths[i+4],bases[i],sizes[i]);
    int fd=open(fault_paths[2],O_WRONLY|O_CREAT|O_TRUNC,0600);
    if(fd>=0){ok&=signal_write(fd,c,sizeof *c);close(fd);}else ok=0;
    char json[512],*p=json;
    p=signal_text(p,"{\"reason\":\"fault\",\"fault_address\":");p=signal_uint(p,address);
    p=signal_text(p,",\"guest_function\":");p=signal_uint(p,guest);
    p=signal_text(p,",\"cpu_size\":");p=signal_uint(p,(uint32_t)sizeof *c);
    p=signal_text(p,",\"native_body\":\"");
    if(name)for(unsigned n=0;name[n]&&n<96;n++){char ch=name[n];if((ch>='0'&&ch<='9')||(ch>='a'&&ch<='z')||(ch>='A'&&ch<='Z')||ch=='_')*p++=ch;}
    p=signal_text(p,"\",\"complete\":");p=signal_text(p,ok?"true":"false");p=signal_text(p,"}\n");
    fd=open(fault_paths[3],O_WRONLY|O_CREAT|O_TRUNC,0600);if(fd>=0){signal_write(fd,json,(size_t)(p-json));close(fd);}
}
