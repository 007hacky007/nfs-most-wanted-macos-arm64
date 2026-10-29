#include "hq_image.h"
#include <stdio.h>
#include <string.h>
int hq_image_hash(const char *,const char *);
int app_runtime_image(const char *,char *,size_t);
static const char base_sha[]="80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c";
static const char official_sha[]="e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb";
static const char hq_sha[]="8393f3487e3e024d6c2196d8adcd3f5b1b38077a893d9161a6f9ac61d587fa19";
static int copy_path(char *output,size_t size,const char *path){
    size_t length=strlen(path);if(length>=size)return 0;memcpy(output,path,length+1);return 1;
}
int hq_image_select(const char *selected,char *output,size_t size,int experimental_full){
    if(hq_image_hash(selected,base_sha))return copy_path(output,size,selected);
    int official=hq_image_hash(selected,official_sha),hq=experimental_full&&hq_image_hash(selected,hq_sha);
    if(!official&&!hq)return 0;
    char candidate[4096];
    if(app_runtime_image(selected,candidate,sizeof candidate)&&hq_image_hash(candidate,base_sha))
        return copy_path(output,size,candidate);
    if(hq){
        const char *slash=strrchr(selected,'/');
        if(slash){int n=snprintf(candidate,sizeof candidate,"%.*s/../runtime.exe",(int)(slash-selected),selected);
            if(n>0&&(size_t)n<sizeof candidate&&hq_image_hash(candidate,base_sha))return copy_path(output,size,candidate);}
    }
    return 0;
}
