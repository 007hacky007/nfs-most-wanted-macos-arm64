#include "../runtime/com.c"
#include <assert.h>
#include <sys/mman.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];int g_gh_com,g_gh_gbuf,g_fxtr,g_dx_in_pass;
uint64_t g_icall_hits;
int g_perflog;
uint64_t g_timer_ticks;
int gheap_bump(void){return 1;}
void mem_commit(uint32_t address,uint32_t size){
    for(uint64_t a=address;a<(uint64_t)address+size;a+=4096){uint32_t page=(uint32_t)a>>14;g_cbits[page>>3]|=1u<<(page&7);}
    uint32_t page=(address+size-1)>>14;g_cbits[page>>3]|=1u<<(page&7);
}
static int metal_on;
int metal_available(void){return metal_on;}
static unsigned observed_blit_src,observed_blit_dst;static int observed_blit_whole;
void metal_blit_rect(unsigned src,unsigned dst,const int*r){observed_blit_src=src;observed_blit_dst=dst;observed_blit_whole=r==NULL;}
static float observed_bias,observed_slope,line_bias,line_slope;
static unsigned line_draws;static TVert observed_vertices[3];
void metal_set_depth_bias(float constant,float slope){observed_bias=constant;observed_slope=slope;}
void metal_set_cull(unsigned mode){(void)mode;}
void metal_draw_tv(const TVert *vertices,unsigned count,unsigned primitive,unsigned texture){
    if(count>=3)memcpy(observed_vertices,vertices,sizeof observed_vertices);(void)primitive;(void)texture;line_bias=observed_bias;line_slope=observed_slope;line_draws++;
}
static unsigned observed_fixed_function;
void metal_set_fixed_function(unsigned mode){observed_fixed_function=mode;}
void metal_set_stage_textures(const unsigned t[16]){(void)t;}
void metal_set_ps_bool(const int b[16]){(void)b;}
void metal_set_ps(int p,const float*c){(void)p;(void)c;}
void metal_set_texproj(const float p[4]){(void)p;}
void metal_set_samplers(const unsigned s[16]){(void)s;}
int gheap_check_block(CPU *cpu,uint32_t address,const char *label){(void)cpu;(void)address;(void)label;return 0;}
unsigned metal_level_pitch(unsigned width,unsigned level,unsigned format){unsigned w=width>>level;if(!w)w=1;return format==0x35545844u?((w+3)/4)*16:w*((format==21 || format==22)?4:1);}
unsigned metal_level_rows(unsigned height,unsigned level,unsigned format){unsigned h=height>>level;if(!h)h=1;return format==0x35545844u?(h+3)/4:h;}
int metal_upload_texture_volume(unsigned handle,unsigned level,const void *data,unsigned pitch,unsigned slice){(void)handle;(void)level;(void)data;(void)pitch;(void)slice;return 1;}
static uint32_t invoke(CPU *cpu,int iface,const char *method,uint32_t self,const uint32_t *args){
    unsigned slot=0;while(slot<g_if[iface].n && strcmp(g_if[iface].m[slot].name,method))slot++;
    assert(slot<g_if[iface].n);cpu->esp=0x10000;MR32(cpu->esp)=0x1234;MR32(cpu->esp+4)=self;
    for(unsigned i=1;i<g_if[iface].m[slot].nargs;i++)MR32(cpu->esp+4+i*4)=args[i-1];
    assert(com_call(cpu,COM_MAGIC|(iface<<16)|slot));
    assert(cpu->esp==0x10004+4*g_if[iface].m[slot].nargs);return cpu->eax;
}


static unsigned issue_flags,backend_handle,query_destroyed;
static uint32_t query_status=1;
unsigned metal_query_create(void){return ++backend_handle;}
void metal_query_destroy(unsigned h){assert(h);query_destroyed++;}
uint32_t metal_query_issue(unsigned h,unsigned flags){assert(h);issue_flags=flags;return flags==1||flags==2?0:0x8876086cu;}
uint32_t metal_query_get_data(unsigned h,unsigned flags,uint32_t*value){assert(h);assert(flags<=1);if(query_status==0&&value)*value=137;return query_status;}
void metal_query_reset(void){}
int main(void){
 g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
 CPU cpu={0};uint32_t device=com_new(IF_DEV,32),a[4]={9,0x18000};g_dev=device;metal_on=1;
 uint64_t before=g_com_live;assert(!invoke(&cpu,IF_DEV,"CreateQuery",device,a));uint32_t query=MR32(0x18000);assert(query&&g_com_live==before+1);
 assert(invoke(&cpu,IF_QUERY,"GetType",query,a)==9);assert(invoke(&cpu,IF_QUERY,"GetDataSize",query,a)==4);
 a[0]=2;assert(!invoke(&cpu,IF_QUERY,"Issue",query,a)&&issue_flags==2);
 a[0]=0x18010;a[1]=4;a[2]=0;MR32(a[0])=0xabcdef;
 assert(invoke(&cpu,IF_QUERY,"GetData",query,a)==1&&MR32(a[0])==0xabcdef);
 query_status=0;assert(!invoke(&cpu,IF_QUERY,"GetData",query,a)&&MR32(a[0])==137);
 a[1]=8;assert(invoke(&cpu,IF_QUERY,"GetData",query,a)==0x8876086cu);a[0]=0;a[1]=4;assert(invoke(&cpu,IF_QUERY,"GetData",query,a)==0x8876086cu);
 a[1]=0;assert(!invoke(&cpu,IF_QUERY,"GetData",query,a));a[2]=2;assert(invoke(&cpu,IF_QUERY,"GetData",query,a)==0x8876086cu);
 a[0]=0;unsigned refs=CH_REF(device);assert(invoke(&cpu,IF_QUERY,"GetDevice",query,a)==0x8876086cu&&CH_REF(device)==refs);
 a[0]=0x18020;assert(!invoke(&cpu,IF_QUERY,"GetDevice",query,a)&&MR32(a[0])==device&&CH_REF(device)==refs+1);com_release(device);
 a[0]=9;a[1]=0;assert(!invoke(&cpu,IF_DEV,"CreateQuery",device,a)&&g_com_live==before+1);
 for(unsigned type=0;type<20;type++)if(type!=9){a[0]=type;a[1]=0x18000;MR32(a[1])=123;assert(invoke(&cpu,IF_DEV,"CreateQuery",device,a)==0x8876086au&&MR32(a[1])==0);}
 assert(invoke(&cpu,IF_QUERY,"AddRef",query,a)==2);assert(invoke(&cpu,IF_QUERY,"Release",query,a)==1&&query_destroyed==0);assert(!invoke(&cpu,IF_QUERY,"Release",query,a)&&query_destroyed==1&&g_com_live==before);
 metal_on=0;a[0]=9;a[1]=0x18000;assert(invoke(&cpu,IF_DEV,"CreateQuery",device,a)==0x8876086au&&MR32(a[1])==0);
 puts("query COM type/capability/size/flags/output/refcount contract passed");return 0;
}
