/* Bounded preparation-only host interfaces. Original bodies are generated locally. */
#include "cpu.h"
#include "hq_config.h"
#include "generated.h"
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <unistd.h>
#include <setjmp.h>

uint8_t *g_mem;
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
static jmp_buf stopped;
static uint32_t stop_site,heap_next;
static unsigned skipped_data,freed_resources;
static uint32_t allocations[2];

static void refuse(CPU *c,uint32_t address){
    fprintf(stderr,"Phase preparation refused target %08x caller %08x\n",address,c&&g_mem&&c->esp<=0x08000000u-4?MR32(c->esp):0);
    exit(77);
}
static int stack_pointer(uint32_t p,unsigned bytes){return p>=0x00e00000u && p<=0x00f00000u-bytes;}
static void require_caller(CPU *c,uint32_t address,uint32_t first,uint32_t second){
    if(!stack_pointer(c->esp,32) || (MR32(c->esp)!=first && (!second || MR32(c->esp)!=second)))refuse(c,address);
}
static void finish(CPU *c,uint32_t result,unsigned bytes){
    c->eax=result;POP32(c->eip);c->esp+=bytes;
}
static int protection_caller(uint32_t caller){
    static const uint32_t allowed[]={0x010136a9u,0x010136ceu,0x010136f3u,0x01013718u,
        0x0100128au,0x010012aau,0x010012cbu,0x010012eau,0x0100190au,0x0100192au,0x0100194bu,0x0100196au,
        0x01001159u,0x0100117bu,0x010011c6u,0x010011e5u,0x0100121au,0x0100123cu,0x01001604u,0x01001627u};
    for(unsigned i=0;i<sizeof allowed/sizeof *allowed;i++)if(caller==allowed[i])return 1;
    return 0;
}
static int resource(uint32_t p){return p && (p==allocations[0] || p==allocations[1]);}
static uint32_t allocate_resource(CPU *c){
    if(MR32(c->esp+4)!=20 || MR32(c->esp+8) || MR32(c->esp+12) || MR32(c->esp+16))refuse(c,0x004653d0u);
    uint32_t p=heap_next;
    if(p!=0x04000000u && p!=0x04000020u)refuse(c,0x004653d0u);
    allocations[p==0x04000000u?0:1]=p;heap_next+=32;
    return p;
}
void guest_hook(CPU *c,uint32_t address){
    if(address!=stop_site)refuse(c,address);
    longjmp(stopped,1);
}
void unsupported_insn(CPU *c,uint32_t address,const char *name){(void)name;refuse(c,address);}
void cpuid_shim(CPU *c){refuse(c,0);}

/* No texture/effect data from this routine feeds the later code-write operands. */
void sub_01010220(CPU *c){
    require_caller(c,0x01010220u,0x0101373bu,0);skipped_data++;finish(c,0,0);
}
void sub_01006a93(CPU *c){
    require_caller(c,0x01006a93u,0x01013817u,0x0101384du);
    if(!resource(MR32(c->esp+4)) || MR32(c->esp+8)!=20)refuse(c,0x01006a93u);
    freed_resources++;finish(c,0,0);
}
/* These original calls occur after the selected stop boundaries. */
void sub_01006af3(CPU *c){refuse(c,0x01006af3u);}
void sub_01009780(CPU *c){refuse(c,0x01009780u);}
void sub_01016f30(CPU *c){refuse(c,0x01016f30u);}

void dispatch_indirect(CPU *c,uint32_t address){
    if(!stack_pointer(c->esp,32))refuse(c,address);
    if(address==0xf0000000u){
        uint32_t p=MR32(c->esp+4),n=MR32(c->esp+8),old=MR32(c->esp+16);
        /* Only the original helpers' guest image operands and stack protection slots. */
        if(!protection_caller(MR32(c->esp)) || p<MW_BASE || p>MW_BASE+MW_IMAGE_SIZE-8 || !n || n>8 ||
           !stack_pointer(old,4) || (MR32(c->esp+12)!=0x40 && MR32(c->esp+12)!=0x20))refuse(c,address);
        MR32(old)=0x20;finish(c,1,16);return;
    }
    if(address==0xf0000001u){
        require_caller(c,address,0x0100131cu,0);
        if(MR32(c->esp+4))refuse(c,address);
        finish(c,MW_BASE,4);return;
    }
    if(address==0xf0000002u){
        uint32_t p=MR32(c->esp+4);
        uint32_t caller=MR32(c->esp);
        if(caller==0x01006a29u){if(p!=0x0102f608u)refuse(c,address);}
        else if((caller!=0x010069ebu && caller!=0x01006a1eu && caller!=0x01006a3du && caller!=0x01006a7au) || p!=0x0102f60cu)refuse(c,address);
        finish(c,0,4);return;
    }
    switch(address){
    case 0x004653d0u:
        require_caller(c,address,0x0101374au,0x010137a1u);
        finish(c,allocate_resource(c),0);return;
    case 0x00455fd0u:
        require_caller(c,address,0x0101376eu,0x010137c0u);
        finish(c,0,0);return;
    case 0x00452380u:
        require_caller(c,address,0x01013786u,0x010137d8u);
        if(!resource(c->ecx) || MR32(c->esp+4) || MR32(c->esp+8) || MR32(c->esp+12))refuse(c,address);
        memset(g_mem+c->ecx,0,20);finish(c,c->ecx,12);return;
    case 0x0045a430u:
        require_caller(c,address,0x01013808u,0x0101383eu);
        if(!resource(c->ecx))refuse(c,address);
        finish(c,0,0);return;
    case 0x0065fd30u:
        require_caller(c,address,0x010138b3u,0);
        /* Original request: path,1,0,0,0; two remaining zeros feed the next call. */
        if(MR32(c->esp+4)!=0x0101f3e0u || MR32(c->esp+8)!=1)refuse(c,address);
        for(unsigned i=3;i<=7;i++)if(MR32(c->esp+i*4))refuse(c,address);
        finish(c,0,0);return;
    case 0x006616f0u:
        require_caller(c,address,0x010138bfu,0);
        if(c->ecx || MR32(c->esp+4) || MR32(c->esp+8))refuse(c,address);
        finish(c,0,8);return;
    case 0x006626b0u:
        require_caller(c,address,0x010138d2u,0);
        if(MR8(0x00925858u) || MR8(0x00925859u))refuse(c,address);
        finish(c,0,0);return;
    case 0x005abad0u:
        require_caller(c,address,0x01007b54u,0);
        finish(c,0,0);return;
    default:refuse(c,address);
    }
}
void dispatch_tail(CPU *c){dispatch_indirect(c,c->eip);}
static void timeout(int sig){(void)sig;_exit(90);}
static void read_image(const char *path,uint32_t base,size_t size){
    FILE *f=fopen(path,"rb");if(!f){fputs("Cannot read phase input\n",stderr);exit(78);}
    if(fread(g_mem+base,1,size,f)!=size || fgetc(f)!=EOF || ferror(f) || fclose(f))exit(78);
}
static void write_image(const char *path){
    FILE *f=fopen(path,"wb");if(!f)exit(78);
    if(fwrite(g_mem+MW_BASE,1,MW_IMAGE_SIZE,f)!=MW_IMAGE_SIZE || fclose(f))exit(78);
}
static void reset_cpu(CPU *c){
    memset(c,0,sizeof *c);c->esp=0x00eff000u;c->fs_base=0x00c00000u;c->fcw=0x027fu;
    MR32(c->fs_base)=0xffffffffu;
}
int main(int argc,char **argv){
    if(argc!=6)return 2;
    signal(SIGALRM,timeout);alarm(10);
    g_mem=calloc(1,0x08000000);if(!g_mem)return 78;
    read_image(argv[1],MW_BASE,MW_IMAGE_SIZE);read_image(argv[2],0x01000000u,0x36000u);
    if(!hq_config_load(argv[3],g_mem+0x0102b550u))return 78;
    MR32(0x0101b018u)=0xf0000000u;MR32(0x0101b01cu)=0xf0000001u;
    for(uint32_t at=0x0101b000u;at<=0x0101b008u;at+=4)MR32(at)=0xf0000002u;
    MR32(0x00c0002cu)=0x00c01000u;MR32(0x0102f644u)=128;
    MR32(0x00c01000u+128*4)=0x00c02000u;MR32(0x00c02004u)=0xffffffffu;
    heap_next=0x04000000u;
    MR32(0x0102f990u)=0x005abad0u;
    CPU cpu,*c=&cpu;reset_cpu(c);
    stop_site=0x01007b72u;
    if(!setjmp(stopped)){PUSH32(0xdeadbeefu);sub_01007b30(c);refuse(c,stop_site);}
    write_image(argv[4]);reset_cpu(c);
    stop_site=0x0101394fu;
    if(!setjmp(stopped)){PUSH32(0xdeadbeefu);sub_01013660(c);refuse(c,stop_site);}
    if(skipped_data!=1 || freed_resources!=2)return 78;
    write_image(argv[5]);free(g_mem);alarm(0);
    puts("Prepared original callback and render code writes; no GUI or GPU work");return 0;
}
