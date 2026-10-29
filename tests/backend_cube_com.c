/* Actual cube vtable calls must preserve the face in the bound target. */
#define main shared_backend_main
#include "backend_com_sm3.c"
#undef main
static unsigned target_calls,targets[12];
unsigned metal_create_texture_cube(unsigned edge,unsigned levels,unsigned format,unsigned rt){assert(edge==16&&levels==2&&format==21&&rt==1);return 7;}
void metal_set_render_target(unsigned target){assert(target_calls<12);targets[target_calls++]=target;}
static uint32_t cube_surface(CPU*cpu,uint32_t cube,unsigned face,unsigned level){
    unsigned slot=0;while(strcmp(g_if[IF_TEX].m[slot].name,"GetSurfaceLevel"))slot++;
    cpu->esp=0x10000;MR32(cpu->esp)=0x1234;MR32(cpu->esp+4)=cube;
    MR32(cpu->esp+8)=face;MR32(cpu->esp+12)=level;MR32(cpu->esp+16)=0x18000;
    assert(com_call(cpu,COM_MAGIC|(IF_TEX<<16)|slot));assert(cpu->esp==0x10014&&!cpu->eax);
    return MR32(0x18000);
}
int main(int argc,char**argv){
    g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
    mem_commit(0x10000,0x10000);CPU cpu={0};uint32_t device=com_new(IF_DEV,16);
    uint32_t args[10]={16,2,0,21,0,0x18000,0};metal_on=1;
    assert(!invoke(&cpu,IF_DEV,"CreateCubeTexture",device,args));uint32_t cube=MR32(0x18000);assert(is_cube_tex(cube));
    uint32_t surfaces[12];
    for(unsigned level=0;level<2;level++)for(unsigned face=0;face<6;face++){
        unsigned i=level*6+face;uint32_t surface=cube_surface(&cpu,cube,face,level);surfaces[i]=surface;
        if(i<10)assert(surface==cube_surface(&cpu,cube,face,level));
        for(unsigned j=0;j<i;j++)assert(surface!=surfaces[j]);
        assert(MR32(surface+44)==face+1&&MR32(surface+48)==level);
        assert(MR32(surface+4)==(16u>>level)&&MR32(surface+8)==(16u>>level));
        args[0]=0;args[1]=surface;assert(!invoke(&cpu,IF_DEV,"SetRenderTarget",device,args));
        assert(targets[i]==(7u|((face+1u)<<16))&&g_cur_rt==7&&g_bind_rt[0]==surface);
    }
    /* A normal 2D child must not acquire a cube face. */
    uint32_t texture=com_new(IF_TEX,TEX_EXTRA);MR32(texture+24)=1;
    uint32_t surface=tex_child(texture,0,0,0);assert(MR32(surface+44)==0);
    if(argc==2){FILE*f=fopen(argv[1],"wb");assert(f);assert(fwrite(targets,sizeof targets,1,f)==1);assert(!fclose(f));}
    puts("cube COM: 12 distinct face/mip surfaces, cached identity, exact stdcall cleanup and packed targets");
    return 0;
}
