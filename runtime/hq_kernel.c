#include "cpu.h"
#include "module.h"
#include <string.h>
#include <stdlib.h>
#include <pthread.h>
#include <wchar.h>
uint32_t win32_module_name_handle(const char *),win32_command_line(void);
uint32_t gheap_alloc(int,uint32_t,int),module_from_address(uint32_t);
void win32_set_last_error(CPU *,uint32_t);

/* A declaration in another module's IAT does not make an API implemented. */
int hq_kernel_export_allowed(const char *name){return strcmp(name,"LCMapStringEx")!=0;}

static pthread_once_t pointer_once=PTHREAD_ONCE_INIT;
static uint32_t pointer_secret;
static void pointer_initialize(void){pointer_secret=arc4random();if(!pointer_secret)pointer_secret=0xa517c3d9u;}
static int wide_utf8(uint32_t p,char *out,size_t capacity){
    size_t used=0;
    if(!p)return 0;
    for(unsigned i=0;i<1024;i++){
        if(!mem_is_committed(p+2*i+1))return 0;
        uint32_t ch=MR16(p+2*i);
        if(!ch){out[used]=0;return 1;}
        if(ch>=0xd800&&ch<=0xdbff){
            if(!mem_is_committed(p+2*(i+1)+1))return 0;
            uint32_t low=MR16(p+2*(++i));if(low<0xdc00||low>0xdfff)return 0;
            ch=0x10000+((ch-0xd800)<<10)+(low-0xdc00);
        }else if(ch>=0xdc00&&ch<=0xdfff)return 0;
        if(used+4>=capacity)return 0;
        if(ch<0x80)out[used++]=(char)ch;
        else if(ch<0x800){out[used++]=(char)(0xc0|(ch>>6));out[used++]=(char)(0x80|(ch&63));}
        else if(ch<0x10000){out[used++]=(char)(0xe0|(ch>>12));out[used++]=(char)(0x80|((ch>>6)&63));out[used++]=(char)(0x80|(ch&63));}
        else{out[used++]=(char)(0xf0|(ch>>18));out[used++]=(char)(0x80|((ch>>12)&63));out[used++]=(char)(0x80|((ch>>6)&63));out[used++]=(char)(0x80|(ch&63));}
    }
    return 0;
}
int hq_kernel_call(CPU *c,const char *name,uint32_t *result){
    if(!strcmp(name,"GetFullPathNameW")){
        uint32_t p=MR32(c->esp),capacity=MR32(c->esp+4),out=MR32(c->esp+8),part=MR32(c->esp+12);
        uint16_t input[1024],full[1100];unsigned count=0,length=0;*result=0;
        if(!p)return 1;
        for(;count<1024;count++){
            if(!mem_is_committed(p+2*count+1)){win32_set_last_error(c,998);return 1;}
            input[count]=MR16(p+2*count);if(!input[count])break;
        }
        if(count==1024){win32_set_last_error(c,206);return 1;}
        if(!(count>=2&&input[1]==':')){
            const char *prefix=(input[0]=='\\'||input[0]=='/')?"C:":"C:\\NFSU2\\";
            for(unsigned i=0;prefix[i];i++)full[length++]=(unsigned char)prefix[i];
        }
        for(unsigned i=0;i<count;i++)full[length++]=input[i]=='/'?'\\':input[i];
        full[length]=0;
        if(!out||capacity<=length){*result=length+1;return 1;}
        if(!mem_is_committed(out)||!mem_is_committed(out+length*2+1)||(part&&!mem_is_committed(part+3))){win32_set_last_error(c,998);return 1;}
        uint32_t leaf=0;
        for(unsigned i=0;i<=length;i++){MR16(out+2*i)=full[i];if(full[i]=='\\'&&i+1<length)leaf=out+2*(i+1);}
        if(part)MR32(part)=leaf;*result=length;return 1;
    }
    if(!strcmp(name,"GetCurrentDirectoryW")){
        const char *path="C:\\NFSU2";uint32_t capacity=MR32(c->esp),out=MR32(c->esp+4);*result=9;
        if(!out||capacity<9)return 1;
        if(!mem_is_committed(out)||!mem_is_committed(out+17)){win32_set_last_error(c,998);*result=0;return 1;}
        for(unsigned i=0;i<9;i++)MR16(out+2*i)=(unsigned char)path[i];*result=8;return 1;
    }

    if(!strcmp(name,"CreateFileW")){
        uint32_t original=MR32(c->esp);char text[4096];*result=0xffffffffu;
        if(!wide_utf8(original,text,sizeof text)){win32_set_last_error(c,1113);return 1;}
        uint32_t path=gheap_alloc(1,(uint32_t)strlen(text)+1,0);
        if(!path){win32_set_last_error(c,8);return 1;}
        memcpy(g_mem+path,text,strlen(text)+1);MR32(c->esp)=path;
        int fileio_call(CPU *,const char *,uint32_t *);void gheap_free(int,uint32_t);
        int handled=fileio_call(c,"CreateFileA",result);
        MR32(c->esp)=original;gheap_free(1,path);return handled;
    }

    if(!strcmp(name,"EncodePointer")||!strcmp(name,"DecodePointer")){
        pthread_once(&pointer_once,pointer_initialize);uint32_t p=MR32(c->esp);unsigned rotate=pointer_secret&31;
        if(name[0]=='E'){p^=pointer_secret;*result=rotate?(p>>rotate)|(p<<(32-rotate)):p;}
        else{if(rotate)p=(p<<rotate)|(p>>(32-rotate));*result=p^pointer_secret;}
        return 1;
    }

    if(!strcmp(name,"CreateEventW")){
        if(MR32(c->esp+12))return 0;
        int win32_ext_call(CPU *,const char *,uint32_t *);
        return win32_ext_call(c,"CreateEventA",result);
    }

    if(!strcmp(name,"GetStartupInfoW")){
        uint32_t p=MR32(c->esp);
        if(!p||!mem_is_committed(p)||!mem_is_committed(p+67))return 0;
        memset(g_mem+p,0,68);MR32(p)=68;*result=0;return 1;
    }

    if(!strcmp(name,"InitializeCriticalSectionEx")){
        if(MR32(c->esp+8)&~0x01000000u)return 0;
        int win32_ext_call(CPU *,const char *,uint32_t *);
        return win32_ext_call(c,"InitializeCriticalSectionAndSpinCount",result);
    }

    if(!strcmp(name,"GetModuleHandleW")){
        uint32_t p=MR32(c->esp);char text[260];*result=0;
        if(!p){*result=win32_module_name_handle(NULL);return 1;}
        unsigned i;
        for(i=0;i<sizeof text;i++){
            if(!mem_is_committed(p+2*i+1)){win32_set_last_error(c,998);return 1;}
            uint16_t ch=MR16(p+2*i);if(ch>127)break;text[i]=(char)ch;if(!ch){*result=win32_module_name_handle(text);break;}
        }
        if(!*result)win32_set_last_error(c,126);return 1;
    }
    if(!strcmp(name,"LoadLibraryExW")){
        if(MR32(c->esp+4)||MR32(c->esp+8)!=0x800)return 0;
        uint32_t p=MR32(c->esp);char text[260];*result=0;
        for(unsigned i=0;p&&i<sizeof text;i++){
            if(!mem_is_committed(p+2*i+1)){win32_set_last_error(c,998);return 1;}
            uint16_t ch=MR16(p+2*i);if(ch>127)break;text[i]=(char)ch;
            if(!ch){*result=win32_module_name_handle(text);break;}
        }
        if(!*result)win32_set_last_error(c,126);return 1;
    }
    if(!strcmp(name,"GetModuleHandleExA")||!strcmp(name,"GetModuleHandleExW")){
        /* Observed FROM_ADDRESS | UNCHANGED_REFCOUNT calls only. Other flags
         * reach the strict unsupported-import path, rather than changing refs. */
        if(MR32(c->esp)!=6)return 0;
        uint32_t address=MR32(c->esp+4),out=MR32(c->esp+8);*result=0;
        if(!out||!mem_is_committed(out+3)){win32_set_last_error(c,998);return 1;}
        uint32_t h=module_from_address(address);
        if(!h&&address>=MW_BASE&&address-MW_BASE<MW_IMAGE_SIZE)h=MW_BASE;
        MR32(out)=h;*result=h!=0;if(!h)win32_set_last_error(c,126);return 1;
    }
    if(!strcmp(name,"GetModuleFileNameW")){
        uint32_t h=MR32(c->esp),out=MR32(c->esp+4),capacity=MR32(c->esp+8);char path[300];*result=0;
        if(!module_file_name(h,path,sizeof path)){
            if(h&&h!=MW_BASE){win32_set_last_error(c,6);return 1;}
            strcpy(path,"C:\\NFSU2\\speed.exe");
        }
        if(!capacity){win32_set_last_error(c,122);return 1;}
        uint32_t length=(uint32_t)strlen(path),copy=length<capacity?length:capacity-1;
        if(!out||!mem_is_committed(out)||!mem_is_committed(out+copy*2+1)){win32_set_last_error(c,998);return 1;}
        for(uint32_t i=0;i<copy;i++)MR16(out+2*i)=(unsigned char)path[i];MR16(out+2*copy)=0;
        *result=length<capacity?length:capacity;if(length>=capacity)win32_set_last_error(c,122);return 1;
    }
    if(!strcmp(name,"GetCommandLineW")){
        static uint32_t wide;uint32_t source=win32_command_line();
        if(!wide){size_t length=strlen((char*)g_mem+source);wide=gheap_alloc(1,(uint32_t)(length+1)*2,0);
            if(!wide)return 0;for(size_t i=0;i<=length;i++)MR16(wide+2*i)=MR8(source+i);}
        *result=wide;return 1;
    }
    return 0;
}
