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
static unsigned observed_targets[4],observed_target_calls;
void metal_set_render_target_at(unsigned slot,unsigned target){assert(slot<4);observed_targets[slot]=target;observed_target_calls++;}
static unsigned observed_ps_outputs[METAL_PS_ENHANCED_CAPACITY];
void metal_set_ps_outputs(int id,unsigned mask){assert(id>0&&id<METAL_PS_ENHANCED_CAPACITY);observed_ps_outputs[id]=mask;}
static unsigned observed_color_write[4],observed_color_write_calls;
void metal_set_color_write(unsigned slot,unsigned mask){assert(slot>0&&slot<4);observed_color_write[slot]=mask;observed_color_write_calls++;}
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
static void rain_fvf(CPU*cpu,uint32_t device){
    uint32_t args[8]={0x244};g_req_w=640;g_req_h=480;g_bb_w=1920;g_bb_h=1080;
    uint32_t backbuffer_args[8]={0,0,0,0x18080};
    assert(!invoke(cpu,IF_DEV,"GetBackBuffer",device,backbuffer_args));uint32_t backbuffer=MR32(0x18080);
    backbuffer_args[0]=0x18090;assert(!invoke(cpu,IF_SURF,"GetDesc",backbuffer,backbuffer_args));
    assert(MR32(0x180a8)==1920&&MR32(0x180ac)==1080);
    uint32_t destination=com_new(IF_SURF,64);MR32(destination+4)=1920;MR32(destination+8)=1080;MR32(destination+28)=91;MR32(destination+40)=2;
    uint32_t copy_args[8]={backbuffer,0,destination,0,2};metal_on=1;
    assert(!invoke(cpu,IF_DEV,"StretchRect",device,copy_args));metal_on=0;
    assert(observed_blit_src==0&&observed_blit_dst==91&&observed_blit_whole);
    invoke(cpu,IF_SURF,"Release",destination,copy_args);
    invoke(cpu,IF_SURF,"Release",backbuffer,backbuffer_args);
    assert(!invoke(cpu,IF_DEV,"SetFVF",device,args));g_tss_raw[1][11]=1;g_cur_vs=0;g_cur_decl=0;g_cur_ps_id=0;
    struct {float x,y,z,rhw;uint32_t color;float u0,v0,u1,v1;} vertices[3]={
        {-.5f,-.5f,.25f,1,0x80402010,.1f,.2f,.7f,.8f},
        {1919.5f,-.5f,.25f,.5f,0x80402010,.3f,.4f,.5f,.6f},
        {-.5f,1079.5f,.25f,1,0x80402010,.2f,.3f,.8f,.9f}};
    memcpy(g_mem+0x19000,vertices,sizeof vertices);
    assert(draw_up(4,3,0x19000,sizeof vertices[0]));
    assert(observed_vertices[0].x==-1&&observed_vertices[0].y==1&&observed_vertices[0].w==1);
    assert(observed_vertices[1].x==2&&observed_vertices[1].y==2&&observed_vertices[1].w==2&&observed_vertices[1].z==.5f);
    assert(observed_vertices[2].x==-1&&observed_vertices[2].y==-1);
    assert(fabsf(observed_vertices[0].r-64/255.f)<1e-6&&fabsf(observed_vertices[0].a-128/255.f)<1e-6);
    assert(observed_vertices[0].t[0][0]==.1f&&observed_vertices[0].t[1][0]==.7f);
    /* Reproduce the bundled binary's exact two-stage sequence. */
    const uint32_t states[2][6]={{4,0,2,4,0,2},{4,2,1,2,1,0}};
    for(unsigned stage=0;stage<2;stage++)for(unsigned state=1;state<=(stage?5:6);state++){
        args[0]=stage;args[1]=state;args[2]=states[stage][state-1];assert(!invoke(cpu,IF_DEV,"SetTextureStageState",device,args));
    }
    assert(draw_up(4,3,0x19000,sizeof vertices[0])&&observed_fixed_function==1);
    args[0]=3;args[1]=0x180d0;assert(!invoke(cpu,IF_DEV,"CreateStateBlock",device,args));uint32_t block=MR32(0x180d0);
    args[0]=0;assert(!invoke(cpu,IF_DEV,"SetVertexDeclaration",device,args));assert(g_fvf_layout==0);
    assert(!invoke(cpu,IF_STATEBLOCK,"Apply",block,args));assert(g_fvf_layout==0x244);
    assert(!invoke(cpu,IF_STATEBLOCK,"Release",block,args));
    args[0]=1;args[1]=1;args[2]=7;assert(!invoke(cpu,IF_DEV,"SetTextureStageState",device,args));
    args[0]=4;args[1]=1;args[2]=0x19000;args[3]=36;
    assert(invoke(cpu,IF_DEV,"DrawPrimitiveUP",device,args)==0x8876086cu);
    g_tss_raw[1][1]=1;
    const char *output=getenv("NFSMW_RAIN_VERTICES_OUT");if(output){FILE*f=fopen(output,"wb");assert(f);assert(fwrite(observed_vertices,1,sizeof observed_vertices,f)==sizeof observed_vertices);fclose(f);}
    args[0]=0;assert(!invoke(cpu,IF_DEV,"SetFVF",device,args));
}

static void texture_mips(CPU *cpu,uint32_t device){
    uint32_t args[10]={8192,8192,0,0,21,1,0x16000,0};
    assert(!invoke(cpu,IF_DEV,"CreateTexture",device,args));uint32_t texture=MR32(0x16000);assert(texture);
    assert(MR32(texture+24)==14);
    uint32_t buffers[14]={0},surfaces[14]={0};
    for(unsigned level=0;level<14;level++){
        args[0]=level;args[1]=0x16010;
        assert(!invoke(cpu,IF_TEX,"GetLevelDesc",texture,args));
        assert(MR32(0x16028)==(8192u>>level) && MR32(0x1602c)==(8192u>>level));
        assert(MR32(0x16014)==1 && MR32(0x1601c)==1);
        assert(!invoke(cpu,IF_TEX,"GetSurfaceLevel",texture,args));surfaces[level]=MR32(0x16010);
        assert(!invoke(cpu,IF_TEX,"GetSurfaceLevel",texture,args));assert(MR32(0x16010)==surfaces[level]);
        args[0]=0x16010;assert(!invoke(cpu,IF_SURF,"GetDesc",surfaces[level],args));
        assert(MR32(0x16028)==(8192u>>level));
        if(level<7)continue;
        args[0]=level;args[1]=0x16010;args[2]=0;args[3]=0;
        assert(!invoke(cpu,IF_TEX,"LockRect",texture,args));buffers[level]=MR32(0x16014);
        for(unsigned previous=7;previous<level;previous++)assert(buffers[level]!=buffers[previous]);
        MR8(buffers[level])=(uint8_t)(level+1);
        assert(!invoke(cpu,IF_TEX,"UnlockRect",texture,args));
        args[0]=0x16010;args[1]=0;args[2]=0;
        assert(!invoke(cpu,IF_SURF,"LockRect",surfaces[level],args));
        assert(MR32(0x16014)==buffers[level] && MR8(MR32(0x16014))==level+1);
        assert(!invoke(cpu,IF_SURF,"UnlockRect",surfaces[level],args));
    }
    for(unsigned level=7;level<14;level++)assert(MR8(buffers[level])==level+1);
    args[0]=14;args[1]=0x16010;assert(invoke(cpu,IF_TEX,"LockRect",texture,args)==0x8876086cu);
    assert(invoke(cpu,IF_TEX,"GetLevelDesc",texture,args)==0x8876086cu);
    for(unsigned level=0;level<14;level++)assert(invoke(cpu,IF_SURF,"Release",surfaces[level],args)>0);
    /* Two GetSurfaceLevel calls each acquired a parent reference. */
    for(unsigned level=0;level<14;level++)assert(invoke(cpu,IF_SURF,"Release",surfaces[level],args)>0);
    assert(!invoke(cpu,IF_TEX,"Release",texture,args));
    for(unsigned level=0;level<14;level++)assert(!com_valid(surfaces[level]));
}

static void npot_mips(CPU *cpu,uint32_t device,unsigned width,unsigned height,unsigned levels){
    uint32_t args[10]={width,height,levels,0,0x35545844u,1,0x17000,0};
    assert(!invoke(cpu,IF_DEV,"CreateTexture",device,args));uint32_t texture=MR32(0x17000),buffers[16]={0};
    for(unsigned level=0;level<levels;level++){
        unsigned w=width>>level,h=height>>level;if(!w)w=1;if(!h)h=1;
        unsigned expected_pitch=((w+3)/4)*16,expected_rows=(h+3)/4;
        args[0]=level;args[1]=0x17010;args[2]=0;args[3]=0;
        assert(!invoke(cpu,IF_TEX,"LockRect",texture,args));assert(MR32(0x17010)==expected_pitch);
        uint32_t buffer=MR32(0x17014);buffers[level]=buffer;
        for(unsigned previous=0;previous<level;previous++)assert(buffers[previous]!=buffer);
        MR8(buffer)=MR8(buffer+expected_pitch*expected_rows-1)=(uint8_t)(level+1);
        assert(!invoke(cpu,IF_TEX,"UnlockRect",texture,args));
    }
    for(unsigned level=0;level<levels;level++)assert(MR8(buffers[level])==level+1);
    assert(!invoke(cpu,IF_TEX,"Release",texture,args));
}

static void volume_formats(CPU *cpu,uint32_t device){
    uint32_t args[10]={4,4,4,1,0,50,1,0x18000,0};
    uint64_t live=g_com_live;MR32(0x18000)=0xdeadbeefu;
    /* L8 is recognized; this isolated COM fixture has no Metal device. */
    assert(invoke(cpu,IF_DEV,"CreateVolumeTexture",device,args)==0x8876086au);
    assert(MR32(0x18000)==0 && g_com_live==live);
    args[5]=41;MR32(0x18000)=0xdeadbeefu;
    assert(invoke(cpu,IF_DEV,"CreateVolumeTexture",device,args)==0x8876086cu);
    assert(MR32(0x18000)==0 && g_com_live==live);
}

static void predefined_states(CPU *cpu,uint32_t device){
    uint32_t args[10]={0,0x19000};MR32(0x19000)=123;uint64_t live=g_com_live;
    assert(invoke(cpu,IF_DEV,"CreateStateBlock",device,args)==0x8876086cu && !MR32(0x19000) && live==g_com_live);
    args[0]=1;args[1]=0;assert(invoke(cpu,IF_DEV,"CreateStateBlock",device,args)==0x8876086cu && live==g_com_live);
    args[0]=256;args[1]=0x1b000;assert(invoke(cpu,IF_DEV,"GetRenderState",device,args)==0x8876086cu);
    args[0]=15;args[1]=0x1b000;args[2]=0x1b004;args[3]=0xffffffffu;assert(invoke(cpu,IF_DEV,"GetStreamSource",device,args)==0x8876086cu);
    args[0]=9;args[1]=0xfffffff0u;assert(invoke(cpu,IF_DEV,"GetLight",device,args)==0x8876086cu);
    uint32_t texture=com_new(IF_TEX,TEX_EXTRA),vertex=com_new(IF_VSHADER,32),pixel=com_new(IF_VSHADER,32),decl=com_new(IF_VDECL,32);
    uint32_t vb=com_new(IF_VB,64),ib=com_new(IF_IB,64);MR32(vertex+12)=3;MR32(pixel+12)=4;MR32(texture+28)=7;
    for(unsigned type=1;type<=3;type++){
        args[0]=15;args[1]=1;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
        args[0]=22;args[1]=2;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
        args[0]=36;args[1]=0x3e800000;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
        args[0]=15;args[1]=1;args[2]=3;assert(!invoke(cpu,IF_DEV,"SetSamplerState",device,args));
        args[1]=13;args[2]=17;assert(!invoke(cpu,IF_DEV,"SetSamplerState",device,args));
        args[0]=7;args[1]=11;args[2]=4;assert(!invoke(cpu,IF_DEV,"SetTextureStageState",device,args));
        args[1]=1;args[2]=8;assert(!invoke(cpu,IF_DEV,"SetTextureStageState",device,args));
        args[0]=15;args[1]=texture;assert(!invoke(cpu,IF_DEV,"SetTexture",device,args));
        args[0]=vertex;assert(!invoke(cpu,IF_DEV,"SetVertexShader",device,args));
        args[0]=pixel;assert(!invoke(cpu,IF_DEV,"SetPixelShader",device,args));
        args[0]=decl;assert(!invoke(cpu,IF_DEV,"SetVertexDeclaration",device,args));
        args[0]=0x112;assert(!invoke(cpu,IF_DEV,"SetFVF",device,args));
        args[0]=15;args[1]=vb;args[2]=12;args[3]=40;assert(!invoke(cpu,IF_DEV,"SetStreamSource",device,args));
        args[0]=ib;assert(!invoke(cpu,IF_DEV,"SetIndices",device,args));
        g_vsk.f[255][3]=.625f;g_vsk.i[15][2]=123;g_vsk.b[15]=1;g_psc[223][3]=.25f;g_psbool[15]=1;g_psint[15][2]=456;
        args[0]=type;args[1]=0x19000;assert(!invoke(cpu,IF_DEV,"CreateStateBlock",device,args));uint32_t block=MR32(0x19000);assert(block);
        assert(CH_REF(texture)==(type==1?3u:2u));
        for(unsigned pass=0;pass<2;pass++){
            if(pass){
                g_psc[223][3]=.875f;g_vsk.f[255][3]=.75f;g_psbool[15]=g_vsk.b[15]=1;
                assert(!invoke(cpu,IF_STATEBLOCK,"Capture",block,args));
            }
            args[0]=15;args[1]=0;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
            args[0]=22;args[1]=3;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
            args[0]=36;args[1]=0x3f400000;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
            args[0]=15;args[1]=1;args[2]=1;assert(!invoke(cpu,IF_DEV,"SetSamplerState",device,args));
            args[1]=13;args[2]=91;assert(!invoke(cpu,IF_DEV,"SetSamplerState",device,args));
            args[0]=7;args[1]=11;args[2]=2;assert(!invoke(cpu,IF_DEV,"SetTextureStageState",device,args));
            args[1]=1;args[2]=9;assert(!invoke(cpu,IF_DEV,"SetTextureStageState",device,args));
            args[0]=15;args[1]=0;assert(!invoke(cpu,IF_DEV,"SetTexture",device,args));
            args[0]=0;assert(!invoke(cpu,IF_DEV,"SetVertexShader",device,args));
            assert(!invoke(cpu,IF_DEV,"SetPixelShader",device,args));assert(!invoke(cpu,IF_DEV,"SetVertexDeclaration",device,args));assert(!invoke(cpu,IF_DEV,"SetFVF",device,args));
            args[0]=15;args[1]=0;args[2]=0;args[3]=0;assert(!invoke(cpu,IF_DEV,"SetStreamSource",device,args));
            args[0]=0;assert(!invoke(cpu,IF_DEV,"SetIndices",device,args));
            g_vsk.f[255][3]=.1f;g_vsk.i[15][2]=7;g_vsk.b[15]=0;g_psc[223][3]=.2f;g_psbool[15]=0;g_psint[15][2]=9;
            assert(!invoke(cpu,IF_STATEBLOCK,"Apply",block,args));
            assert(g_rs[15]==(type!=3?1u:0u) && g_rs[22]==(type!=2?2u:3u));
            assert(g_rs[36]==0x3e800000 && g_smp_raw[15][1]==(type!=3?3u:1u) && g_smp_raw[15][13]==(type!=2?17u:91u));
            assert(g_tss_raw[7][11]==4 && g_tss_raw[7][1]==(type!=3?8u:9u));
            assert(g_raw_vs==(type!=2?vertex:0) && g_raw_ps==(type!=3?pixel:0) && g_cur_decl==(type!=2?decl:0));
            assert(g_cur_fvf==(type!=2?0x112u:0));
            assert(g_raw_tex[15]==(type==1?texture:0) && g_tex_stage[15]==(type==1?7u:0));
            assert(g_bind_vb[15]==(type==1?vb:0) && g_ib_obj==(type==1?ib:0));
            if(type==1)assert(g_stream_offset[15]==12 && g_stream_stride[15]==40);
            assert(g_vsk.f[255][3]==(type!=2?(pass?.75f:.625f):.1f) && g_vsk.i[15][2]==(type!=2?123:7));
            assert(g_vsk.b[15]==(type!=2) && g_psbool[15]==(type!=3));
            assert(g_psc[223][3]==(type!=3?(pass?.875f:.25f):.2f));
            assert(g_psint[15][2]==(type!=3?456:9));
            args[0]=15;args[1]=0x1b000;assert(!invoke(cpu,IF_DEV,"GetRenderState",device,args));assert(MR32(0x1b000)==(type!=3));
            args[0]=15;args[1]=1;args[2]=0x1b000;assert(!invoke(cpu,IF_DEV,"GetSamplerState",device,args));assert(MR32(0x1b000)==(type!=3?3u:1u));
            args[0]=7;args[1]=11;assert(!invoke(cpu,IF_DEV,"GetTextureStageState",device,args));assert(MR32(0x1b000)==4);
            args[0]=15;args[1]=0x1b000;assert(!invoke(cpu,IF_DEV,"GetTexture",device,args));assert(MR32(0x1b000)==(type==1?texture:0));if(MR32(0x1b000))com_release(MR32(0x1b000));
            args[0]=15;args[1]=0x1b000;args[2]=0x1b004;args[3]=0x1b008;assert(!invoke(cpu,IF_DEV,"GetStreamSource",device,args));
            assert(MR32(0x1b000)==(type==1?vb:0) && MR32(0x1b004)==(type==1?12u:0) && MR32(0x1b008)==(type==1?40u:0));if(MR32(0x1b000))com_release(MR32(0x1b000));
            args[0]=255;args[1]=0x1b000;args[2]=1;assert(!invoke(cpu,IF_DEV,"GetVertexShaderConstantF",device,args));assert(MRF32(0x1b00c)==(type!=2?(pass?.75f:.625f):.1f));
            args[0]=15;assert(!invoke(cpu,IF_DEV,"GetVertexShaderConstantI",device,args));assert(MR32(0x1b008)==(type!=2?123u:7u));
            assert(!invoke(cpu,IF_DEV,"GetVertexShaderConstantB",device,args));assert(MR32(0x1b000)==(type!=2));
            assert(!invoke(cpu,IF_DEV,"GetPixelShaderConstantI",device,args));assert(MR32(0x1b008)==(type!=3?456u:9u));
            const char *getters[]={"GetVertexShader","GetPixelShader","GetVertexDeclaration","GetIndices"};
            uint32_t expected[]={type!=2?vertex:0,type!=3?pixel:0,type!=2?decl:0,type==1?ib:0};
            for(unsigned i=0;i<4;i++){
                args[0]=0x1b000;assert(!invoke(cpu,IF_DEV,getters[i],device,args));assert(MR32(0x1b000)==expected[i]);if(expected[i])com_release(expected[i]);
            }
            assert(!invoke(cpu,IF_DEV,"GetFVF",device,args));assert(MR32(0x1b000)==(type!=2?0x112u:0));
        }
        assert(!invoke(cpu,IF_STATEBLOCK,"Release",block,args));
        args[0]=15;args[1]=0;assert(!invoke(cpu,IF_DEV,"SetTexture",device,args));
        args[0]=15;assert(!invoke(cpu,IF_DEV,"SetStreamSource",device,args));args[0]=0;assert(!invoke(cpu,IF_DEV,"SetIndices",device,args));
    }
    args[0]=0;invoke(cpu,IF_DEV,"SetVertexShader",device,args);invoke(cpu,IF_DEV,"SetPixelShader",device,args);invoke(cpu,IF_DEV,"SetVertexDeclaration",device,args);
    com_release(texture);com_release(vertex);com_release(pixel);com_release(decl);com_release(vb);com_release(ib);
    uint32_t held=com_new(IF_VSHADER,32);args[0]=held;invoke(cpu,IF_DEV,"SetVertexShader",device,args);
    args[0]=3;args[1]=0x19000;assert(!invoke(cpu,IF_DEV,"CreateStateBlock",device,args));uint32_t block=MR32(0x19000);
    com_release(held);assert(com_valid(held) && CH_REF(held)==1);
    assert(!invoke(cpu,IF_STATEBLOCK,"Capture",block,args));assert(com_valid(held) && CH_REF(held)==1);
    args[0]=0;invoke(cpu,IF_DEV,"SetVertexShader",device,args);assert(!invoke(cpu,IF_STATEBLOCK,"Release",block,args));assert(CH_REF(held)==0);
}

static void depth_bias_state(CPU *cpu,uint32_t device){
    uint32_t args[10]={175,0x40000000};assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
    float bias=-.01f;args[0]=195;memcpy(&args[1],&bias,4);assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
    depth_bias_push();assert(observed_bias==-.01f && observed_slope==2);
    TVert line[2]={{0}};line[0].w=line[1].w=1;line[1].x=.5f;
    draw_lines(line,2,2);assert(line_draws==1 && !line_bias && !line_slope);
    assert(observed_bias==-.01f && observed_slope==2);
    for(unsigned type=1;type<=3;type++){
        args[0]=type;args[1]=0x19000;assert(!invoke(cpu,IF_DEV,"CreateStateBlock",device,args));uint32_t block=MR32(0x19000);
        args[0]=175;args[1]=0;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
        args[0]=195;assert(!invoke(cpu,IF_DEV,"SetRenderState",device,args));
        assert(!invoke(cpu,IF_STATEBLOCK,"Apply",block,args));depth_bias_push();
        assert(observed_bias==(type!=3?-.01f:0) && observed_slope==(type!=3?2:0));
        assert(!invoke(cpu,IF_STATEBLOCK,"Release",block,args));
    }
}

static void predefined_auxiliary(CPU *cpu,uint32_t device){
    const char *sets[]={"SetTransform","SetMaterial","SetLight","SetClipPlane","SetViewport","SetScissorRect"};
    const char *gets[]={"GetTransform","GetMaterial","GetLight","GetClipPlane","GetViewport","GetScissorRect"};
    const unsigned sizes[]={64,68,104,16,24,16},keys[]={2,0,9,2,0,0};
    uint32_t args[10];
    for(unsigned type=1;type<=3;type++){
        for(unsigned k=0;k<6;k++){
            memset(g_mem+0x1a000+k*128,17+k,sizes[k]);
            args[0]=keys[k]?keys[k]:0x1a000+k*128;args[1]=0x1a000+k*128;
            assert(!invoke(cpu,IF_DEV,sets[k],device,args));
        }
        args[0]=9;args[1]=1;assert(!invoke(cpu,IF_DEV,"LightEnable",device,args));
        args[0]=3;args[1]=2;assert(!invoke(cpu,IF_DEV,"SetStreamSourceFreq",device,args));
        args[0]=0x40000000;assert(!invoke(cpu,IF_DEV,"SetNPatchMode",device,args));
        args[0]=type;args[1]=0x19000;assert(!invoke(cpu,IF_DEV,"CreateStateBlock",device,args));uint32_t block=MR32(0x19000);
        for(unsigned k=0;k<6;k++){
            memset(g_mem+0x1a000+k*128,33+k,sizes[k]);
            args[0]=keys[k]?keys[k]:0x1a000+k*128;args[1]=0x1a000+k*128;
            assert(!invoke(cpu,IF_DEV,sets[k],device,args));
        }
        args[0]=9;args[1]=0;assert(!invoke(cpu,IF_DEV,"LightEnable",device,args));
        args[0]=3;args[1]=8;assert(!invoke(cpu,IF_DEV,"SetStreamSourceFreq",device,args));
        args[0]=0x40800000;assert(!invoke(cpu,IF_DEV,"SetNPatchMode",device,args));
        assert(!invoke(cpu,IF_STATEBLOCK,"Apply",block,args));
        for(unsigned k=0;k<6;k++){
            args[0]=keys[k]?keys[k]:0x1b000;args[1]=0x1b000;memset(g_mem+0x1b000,0xcc,104);
            assert(!invoke(cpu,IF_DEV,gets[k],device,args));
            unsigned expected=(type==1 || (type==3 && k==2)?17:33)+k;
            for(unsigned i=0;i<sizes[k];i++)assert(MR8(0x1b000+i)==expected);
        }
        args[0]=9;args[1]=0x1b000;assert(!invoke(cpu,IF_DEV,"GetLightEnable",device,args));assert(MR32(0x1b000)==(type!=2));
        args[0]=3;assert(!invoke(cpu,IF_DEV,"GetStreamSourceFreq",device,args));assert(MR32(0x1b000)==(type!=2?2u:8u));
        assert(!invoke(cpu,IF_DEV,"GetNPatchMode",device,args));assert(cpu->st[cpu->top&7]==(type!=2?2.f:4.f));
        assert(!invoke(cpu,IF_STATEBLOCK,"Release",block,args));
    }
}

static void stateblock_light_membership(CPU *cpu,uint32_t device){
    uint32_t args[10];
    for(unsigned type=1;type<=3;type+=2){
        unsigned old=200+type*2,new=old+1;
        memset(g_mem+0x1a000,17,104);args[0]=old;args[1]=0x1a000;assert(!invoke(cpu,IF_DEV,"SetLight",device,args));
        args[0]=type;args[1]=0x19000;assert(!invoke(cpu,IF_DEV,"CreateStateBlock",device,args));uint32_t block=MR32(0x19000);
        memset(g_mem+0x1a000,33,104);args[0]=new;args[1]=0x1a000;assert(!invoke(cpu,IF_DEV,"SetLight",device,args));
        assert(!invoke(cpu,IF_STATEBLOCK,"Apply",block,args));
        args[0]=new;args[1]=0x1b000;assert(!invoke(cpu,IF_DEV,"GetLight",device,args));assert(MR8(0x1b000)==33);
        assert(!invoke(cpu,IF_STATEBLOCK,"Capture",block,args));
        memset(g_mem+0x1a000,55,104);args[0]=new;args[1]=0x1a000;assert(!invoke(cpu,IF_DEV,"SetLight",device,args));
        assert(!invoke(cpu,IF_STATEBLOCK,"Apply",block,args));
        args[0]=new;args[1]=0x1b000;assert(!invoke(cpu,IF_DEV,"GetLight",device,args));assert(MR8(0x1b000)==55);
        assert(!invoke(cpu,IF_DEV,"BeginStateBlock",device,args));
        assert(invoke(cpu,IF_STATEBLOCK,"Capture",block,args)==0x8876086cu);
        assert(invoke(cpu,IF_STATEBLOCK,"Apply",block,args)==0x8876086cu);
        args[0]=0x19004;assert(!invoke(cpu,IF_DEV,"EndStateBlock",device,args));
        assert(!invoke(cpu,IF_STATEBLOCK,"Release",MR32(0x19004),args));
        assert(!invoke(cpu,IF_STATEBLOCK,"Release",block,args));
    }
}

int main(void){
    g_mem=mmap(NULL,GSZ,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(g_mem!=MAP_FAILED);
    mem_commit(0x10000,0x10000);CPU cpu={0};uint32_t device=com_new(IF_DEV,16);
    volume_formats(&cpu,device);
    predefined_states(&cpu,device);
    predefined_auxiliary(&cpu,device);
    stateblock_light_membership(&cpu,device);
    depth_bias_state(&cpu,device);
    rain_fvf(&cpu,device);texture_mips(&cpu,device);
    npot_mips(&cpu,device,758,1200,11);npot_mips(&cpu,device,1600,2262,12);
    float values[4]={.1f,.2f,.3f,.4f};memcpy(g_mem+0x11000,values,16);
    uint32_t args[10]={223,0x11000,1};assert(!invoke(&cpu,IF_DEV,"SetPixelShaderConstantF",device,args));
    assert(g_psc[223][3]==.4f);
    MR32(0x11000)=1;args[0]=15;assert(!invoke(&cpu,IF_DEV,"SetPixelShaderConstantB",device,args));assert(g_psbool[15]==1);
    args[0]=6;args[1]=0;assert(!invoke(&cpu,IF_DEV,"SetTexture",device,args));
    assert(!invoke(&cpu,IF_DEV,"BeginStateBlock",device,args));
    MR32(0x11000)=1;args[0]=15;args[1]=0x11000;args[2]=1;
    assert(!invoke(&cpu,IF_DEV,"SetPixelShaderConstantB",device,args));
    args[0]=0x13000;assert(!invoke(&cpu,IF_DEV,"EndStateBlock",device,args));uint32_t block=MR32(0x13000);
    MR32(0x11000)=0;args[0]=15;args[1]=0x11000;args[2]=1;
    assert(!invoke(&cpu,IF_DEV,"SetPixelShaderConstantB",device,args));
    assert(!invoke(&cpu,IF_STATEBLOCK,"Apply",block,args));assert(g_psbool[15]==1);
    /* A volume must have its real interface, mip description and box layout. */
    uint32_t volume=com_new(IF_VOLTEX,256);MR32(volume+4)=4;MR32(volume+8)=8;MR32(volume+12)=4;MR32(volume+20)=21;MR32(volume+24)=4;
    args[0]=1;args[1]=0x12000;assert(!invoke(&cpu,IF_VOLTEX,"GetLevelDesc",volume,args));
    assert(MR32(0x12010)==2 && MR32(0x12014)==4 && MR32(0x12018)==2);
    args[0]=1;args[1]=0x12000;args[2]=0;args[3]=0;
    assert(!invoke(&cpu,IF_VOLTEX,"LockBox",volume,args));assert(MR32(0x12000)==8 && MR32(0x12004)==32 && MR32(0x12008));
    assert(invoke(&cpu,IF_VOLTEX,"LockBox",volume,args)==0x8876086cu);
    assert(!invoke(&cpu,IF_VOLTEX,"UnlockBox",volume,args));
    args[0]=4;assert(invoke(&cpu,IF_VOLTEX,"LockBox",volume,args)==0x8876086cu);
    args[0]=2;args[1]=0x12000;assert(!invoke(&cpu,IF_VOLTEX,"GetVolumeLevel",volume,args));uint32_t child=MR32(0x12000);
    args[0]=0x12010;assert(!invoke(&cpu,IF_VOLUME,"GetDesc",child,args));assert(MR32(0x12020)==1 && MR32(0x12024)==2 && MR32(0x12028)==1);
    g_psbool[15]=1;args[0]=0;assert(!invoke(&cpu,IF_DEV,"Reset",device,args));assert(g_psbool[15]==0);
    uint32_t destination=com_new(IF_VOLTEX,256);
    MR32(destination+4)=4;MR32(destination+8)=8;MR32(destination+12)=4;MR32(destination+20)=21;MR32(destination+24)=4;MR32(destination+28)=2;
    memset(g_mem+MR32(volume+36),7,64);args[0]=volume;args[1]=destination;
    assert(!invoke(&cpu,IF_DEV,"UpdateTexture",device,args));
    args[0]=1;args[1]=0x12000;args[2]=0;args[3]=0x10;
    assert(!invoke(&cpu,IF_VOLTEX,"LockBox",destination,args));
    uint32_t copied=MR32(0x12008);assert(MR8(copied)==7 && MR8(copied+63)==7);
    assert(!invoke(&cpu,IF_VOLTEX,"UnlockBox",destination,args));
    uint32_t unsupported[]={0xffff0300,0x01000019,0xa0e41000,0xffff};
    memcpy(g_mem+0x15000,unsupported,sizeof unsupported);args[0]=0x15000;args[1]=0x15100;MR32(0x15100)=0xdeadbeefu;
    uint64_t live=g_com_live;uint32_t rejected=invoke(&cpu,IF_DEV,"CreatePixelShader",device,args);
    assert(rejected==0x8876086cu && MR32(0x15100)==0 && g_com_live==live);
    fill_caps(0x14000);
    const char *mode=getenv("NFSMW_MODE");
    if(mode && !strcmp(mode,"full")){
        assert(MR32(0x140c4)==0xfffe0300u && MR32(0x140cc)==0xffff0300u);
        assert(MR32(0x140fc)==24 && MR32(0x14100)==32 && MR32(0x14110)==32 && MR32(0x1412c)==32768);
    }else assert(MR32(0x140c4)==0xfffe0200u && MR32(0x140cc)==0xffff0200u);
    puts("PASS: COM shader constants, typed state blocks, depth bias and texture layouts");
}

/* This fixture exercises COM with an unavailable query GPU backend. */
void metal_query_reset(void){}
unsigned metal_query_create(void){return 0;}
void metal_query_destroy(unsigned handle){(void)handle;}
uint32_t metal_query_issue(unsigned handle,unsigned flags){(void)handle;(void)flags;return 0x8876086au;}
uint32_t metal_query_get_data(unsigned handle,unsigned flags,uint32_t *value){(void)handle;(void)flags;(void)value;return 0x8876086au;}
