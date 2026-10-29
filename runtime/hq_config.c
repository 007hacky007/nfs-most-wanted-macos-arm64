#include "hq_config.h"
#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "hq_config_fields.h"
#include "hq_xenon_fields.h"

static char *trim(char *s){
    while(isspace((unsigned char)*s))s++;
    size_t n=strlen(s);while(n&&isspace((unsigned char)s[n-1]))s[--n]=0;
    return s;
}

static int load_fields(const char *path,const HQField *fields,unsigned count,uint8_t *output,unsigned size,int required,uint64_t *present){
    FILE *f=fopen(path,"rb");if(!f)return 0;
    uint8_t *data=calloc(1,size);if(!data){fclose(f);return 0;}uint64_t seen=0;
    char line[1024],section[64]="";int valid=1;
    while(valid&&fgets(line,sizeof line,f)){
        if(!strchr(line,'\n')&&!feof(f)){valid=0;break;}
        char *s=trim(line);if(!*s||*s=='#'||*s==';'||!strncmp(s,"//",2))continue;
        if(*s=='['){char *end=strchr(s,']');if(!end){valid=0;break;}*end=0;snprintf(section,sizeof section,"%s",trim(s+1));continue;}
        char *equal=strchr(s,'=');if(!equal){valid=0;break;}*equal=0;
        char *key=trim(s),*value=trim(equal+1);
        if(*value=='"'){
            char *end=strrchr(++value,'"');if(!end){valid=0;break;}*end=0;
        }else{
            for(char *q=value;*q;q++)if(q>value&&isspace((unsigned char)q[-1])&&(*q=='#'||*q==';'||!strncmp(q,"//",2))){*q=0;break;}
            value=trim(value);
        }
        for(unsigned i=0;i<count;i++){
            const HQField *field=&fields[i];
            if(strcasecmp(section,field->section)||strcasecmp(key,field->key))continue;
            errno=0;char *end;
            unsigned length=field->type=='s'?(field->length?field->length:256):field->type=='b'?1:4;
            if(field->offset>size||length>size-field->offset){valid=0;break;}
            if(field->type=='s'){
                if(strlen(value)>=length){valid=0;break;}
                memset(data+field->offset,0,length);memcpy(data+field->offset,value,strlen(value));
            }else if(field->type=='f'){
                float number=strtof(value,&end);
                if(errno||end==value||*trim(end)||!isfinite(number)){valid=0;break;}
                memcpy(data+field->offset,&number,4);
            }else{
                long number=strtol(value,&end,0);
                if(errno||end==value||*trim(end)||number<INT32_MIN||number>INT32_MAX){valid=0;break;}
                if(field->type=='b')data[field->offset]=number!=0;
                else{int32_t integer=(int32_t)number;memcpy(data+field->offset,&integer,4);}
            }
            seen|=1ull<<i;break;
        }
    }
    valid=valid&&!ferror(f)&&(!required||seen==((1ull<<count)-1));
    fclose(f);if(valid){memcpy(output,data,size);if(present)*present=seen;}free(data);return valid;
}

int hq_config_load(const char *path,uint8_t output[HQ_CONFIG_SIZE]){
    return load_fields(path,hq_fields,sizeof hq_fields/sizeof *hq_fields,output,HQ_CONFIG_SIZE,1,NULL);
}
int hq_config_xenon_load(const char *path,uint8_t output[HQ_XENON_CONFIG_SIZE],uint64_t *present){
    return load_fields(path,hq_xenon_fields,sizeof hq_xenon_fields/sizeof *hq_xenon_fields,output,HQ_XENON_CONFIG_SIZE,0,present);
}
