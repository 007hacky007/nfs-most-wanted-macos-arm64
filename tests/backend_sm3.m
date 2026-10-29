/* Exercise the actual Metal backend without opening a window or the game. */
#include "../runtime/metal.m"
#include <assert.h>
#include <sys/mman.h>
#include <unistd.h>
int g_perflog;
float enh_blur(void){return 1.f;}
_Atomic int g_pl_thumb_req;
char g_pl_dir[900];
_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;
__strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX];
uint8_t g_texrep_k[TEXREP_MAXTEX];
#include "vsemu.h"
#define REG(t,n) (0x80000000u|(((t)&7u)<<28)|(((t)&24u)<<8)|(n))
#define DST(t,n,m) (REG(t,n)|((m)<<16))
#define SRC(t,n) (REG(t,n)|0x00e40000u)
static void rain_fixed_function_reference(const char *input){
    NSError *error=nil;g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:&error];assert(g_lib);
    NSString *vertex=@"vertex VOut rain_vertex(uint vid [[vertex_id]]) { VOut o={}; float2 xy[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};o.pos=float4(xy[vid],.5,1);o.col0=float4(.8,.6,.4,.5);o.uv0=float4(.25,.25,0,1);o.uv1=float4(.75,.75,0,1);o.fog=1;return o;}";
    TVert captured[3];if(input){FILE*f=fopen(input,"rb");assert(f);assert(fread(captured,1,sizeof captured,f)==sizeof captured);fclose(f);
        vertex=@"struct RainVertex {float4 pos,col0,col1;float4 uv[8];float4 color[4];};vertex VOut rain_vertex(uint vid [[vertex_id]],constant RainVertex*v [[buffer(0)]]){VOut o={};o.pos=v[vid].pos;o.col0=v[vid].col0;o.uv0=v[vid].uv[0];o.uv1=v[vid].uv[1];o.fog=1;return o;}";}
    id<MTLLibrary> library=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:vertex] options:nil error:&error];assert(library);g_vsfn[56]=[library newFunctionWithName:@"rain_vertex"];
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:2 height:2 mipmapped:NO];td.storageMode=MTLStorageModeShared;
    id<MTLTexture> mask=[g_dev newTextureWithDescriptor:td],scene=[g_dev newTextureWithDescriptor:td];
    float a[4][4]={{.5,.75,1,.8},{0,0,0,0},{0,0,0,0},{0,0,0,0}},b[4][4]={{1,0,0,1},{0,1,0,1},{0,0,1,1},{.25,.5,.75,.1}};
    [mask replaceRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0 withBytes:a bytesPerRow:32];[scene replaceRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0 withBytes:b bytesPerRow:32];
#if NFS_ENHANCED
    g_tex[7]=scene;g_hd_ow[7]=g_hd_oh[7]=1;
    MDraw translated={.tex=7,.ps=1};float scale,level;pixel_aux_constants(&translated,1,&scale,&level);assert(scale==1&&level==1);
#endif
    td.pixelFormat=MTLPixelFormatBGRA8Unorm;td.width=input?1920:4;td.height=input?1080:2;td.usage=MTLTextureUsageRenderTarget;
    id<MTLTexture> output=[g_dev newTextureWithDescriptor:td];td.pixelFormat=MTLPixelFormatDepth32Float;td.storageMode=MTLStorageModePrivate;id<MTLTexture> depth=[g_dev newTextureWithDescriptor:td];
    MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;id<MTLSamplerState> sampler=[g_dev newSamplerStateWithDescriptor:sd];
    id<MTLCommandQueue> queue=[g_dev newCommandQueue];
    for(unsigned mode=0;mode<4;mode++){
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];pass.colorAttachments[0].texture=output;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.depthAttachment.texture=depth;pass.depthAttachment.loadAction=MTLLoadActionClear;
        float background[4]={0};if(mode==3){background[0]=.2;background[1]=.3;background[2]=.4;background[3]=.7;pass.colorAttachments[0].clearColor=MTLClearColorMake(.2,.3,.4,.7);}
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        struct {float aref,usec,mode,pad;float proj[4],c[224][4],fog[4];int booleans[16];} constants={0};MDraw draw={.tex=7,.fixed_function=mode?1:0};pixel_aux_constants(&draw,1,&constants.mode,&constants.pad);constants.aref=mode==2?.41f:0;
        if(input)[encoder setVertexBytes:captured length:sizeof captured atIndex:0];
        [encoder setRenderPipelineState:pso_for(metal_shader_key(0,56)|(15u<<14)|(mode==3?(1u|(5u<<1)|(6u<<6)|(1u<<11)):0))];[encoder setFragmentBytes:&constants length:sizeof constants atIndex:0];
        [encoder setFragmentTexture:mask atIndex:0];[encoder setFragmentTexture:scene atIndex:1];for(unsigned i=0;i<2;i++)[encoder setFragmentSamplerState:sampler atIndex:i];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];[command commit];[command waitUntilCompleted];assert(command.status==MTLCommandBufferStatusCompleted);
        float expected[4]={.4,.45,.4,.4};if(input){expected[0]=64/255.f*.5f;expected[1]=32/255.f*.75f;expected[2]=16/255.f;expected[3]=128/255.f*.8f;}
        if(mode==1||mode==3){expected[0]*=.25;expected[1]*=.5;expected[2]*=.75;}if(mode==2)memset(expected,0,sizeof expected);
        if(mode==3){float alpha=expected[3];for(unsigned c=0;c<4;c++)expected[c]=expected[c]*alpha+background[c]*(1-alpha);}
        unsigned points[8][2]={{0,0},{959,0},{0,539},{480,270},{319,239},{1440,810},{1919,1079},{1800,900}};
        unsigned channel[4]={2,1,0,3};for(unsigned pixel=0;pixel<8;pixel++){
            unsigned x=input?points[pixel][0]:pixel%4,y=input?points[pixel][1]:pixel/4;uint8_t actual[4];
            [output getBytes:actual bytesPerRow:4 fromRegion:MTLRegionMake2D(x,y,1,1) mipmapLevel:0];
            for(unsigned c=0;c<4;c++)assert(fabsf(actual[channel[c]]/255.f-(input&&pixel>=5?background[c]:expected[c]))<1.1f/255.f);
        }
    }
}

static void depth_bias_reference(void){
    uint32_t code[]={0xffff0200,0x02000001,DST(8,0,15),SRC(2,0),0xffff};
    VSProg *program=vs_compile(code,sizeof code/4);assert(program);char source[65536];assert(ps_to_msl(program,53,source,sizeof source));vs_free(program);metal_register_ps(53,source);assert(g_psfn[53]);
    NSString *vertex=@"vertex VOut depth_vertex(uint vid [[vertex_id]],constant float2 &p [[buffer(0)]]) { VOut o={}; float2 xy[3]={float2(-1,-1),float2(3,-1),float2(-1,3)}; o.pos=float4(xy[vid],p.x+xy[vid].x*p.y,1); o.fog=1; return o; }";
    NSError *error=nil;id<MTLLibrary> library=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:vertex] options:nil error:&error];assert(library);
    g_vsfn[54]=[library newFunctionWithName:@"depth_vertex"];
    g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:&error];assert(g_lib && metal_depth_fragment(0));
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float width:4 height:4 mipmapped:NO];td.storageMode=MTLStorageModePrivate;td.usage=MTLTextureUsageRenderTarget;id<MTLTexture> depth=[g_dev newTextureWithDescriptor:td];assert(depth);
    td.pixelFormat=MTLPixelFormatBGRA8Unorm;td.storageMode=MTLStorageModeShared;id<MTLTexture> color=[g_dev newTextureWithDescriptor:td];assert(color);
    MTLDepthStencilDescriptor *ds=[MTLDepthStencilDescriptor new];ds.depthCompareFunction=MTLCompareFunctionAlways;ds.depthWriteEnabled=YES;
    id<MTLBuffer> output=[g_dev newBufferWithLength:1024 options:MTLResourceStorageModeShared];id<MTLCommandQueue> queue=[g_dev newCommandQueue];
    struct {float head[8];float c[224][4];float fog[4];int b[16];} constants={0};constants.c[0][0]=.2f;constants.c[0][1]=.3f;constants.c[0][2]=.4f;constants.c[0][3]=.75f;
    const float cases[][4]={{.25f,0,.01f,0},{.5f,0,.01f,0},{.25f,0,-.01f,0},{.5f,0,-.01f,0},{.4f,.02f,0,2},{.4f,.02f,.03f,2},{.4f,.02f,0,-2},{.4f,.02f,-.03f,-2}};
    for(unsigned i=0;i<9;i++){
        const float *test=cases[i<8?i:5];constants.head[0]=i==8?1:0;
        uint64_t key=metal_shader_key(53,54)|(15u<<14);if(test[2])key|=1ull<<53;
        id<MTLRenderPipelineState> pipeline=pso_for(key);assert(pipeline);
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];pass.depthAttachment.texture=depth;pass.depthAttachment.loadAction=MTLLoadActionClear;pass.depthAttachment.storeAction=MTLStoreActionStore;pass.depthAttachment.clearDepth=1;
        pass.colorAttachments[0].texture=color;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,0);
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        [encoder setRenderPipelineState:pipeline];[encoder setDepthStencilState:[g_dev newDepthStencilStateWithDescriptor:ds]];
        [encoder setVertexBytes:test length:8 atIndex:0];[encoder setFragmentBytes:&constants length:sizeof constants atIndex:0];
        metal_apply_depth_bias(encoder,test[2],test[3]);
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];
        id<MTLBlitCommandEncoder> blit=[command blitCommandEncoder];[blit copyFromTexture:depth sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(4,4,1) toBuffer:output destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:1024];[blit endEncoding];[command commit];[command waitUntilCompleted];assert(command.status==MTLCommandBufferStatusCompleted);
        const float *actual=output.contents;
        for(int y=0;y<4;y++)for(int x=0;x<4;x++){
            float expected=i==8?1:test[0]+(-.75f+.5f*x)*test[1]+test[2]+fabsf(test[1])*.5f*test[3];
            if(fabsf(actual[y*64+x]-expected)>1e-5f)fprintf(stderr,"depth case%u xy%d,%d: %.9g expected%.9g\n",i,x,y,actual[y*64+x],expected);
            assert(fabsf(actual[y*64+x]-expected)<1e-5f);
        }
        uint8_t bgra[4];[color getBytes:bgra bytesPerRow:4 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
        int channel[4]={2,1,0,3};for(int c=0;c<4;c++)assert(fabsf(bgra[channel[c]]/255.f-(i==8?0:constants.c[0][c]))<=1/255.f);
    }
    NSString *mrt=NFS_ENHANCED?@"":@"struct PSOut {float4 c0 [[color(0)]],c1 [[color(1)]],c2 [[color(2)]],c3 [[color(3)]];};\n";
    mrt=[mrt stringByAppendingString:@"fragment PSOut ps_55(VOut i [[stage_in]],constant PSPar &P [[buffer(0)]]) { return {P.c[0],P.c[1],P.c[2],P.c[3]}; }\n"];
    metal_register_ps(55,mrt.UTF8String);assert(g_psfn[55] && metal_depth_fragment(55));
}

static void legacy_color_remap(void){
    uint32_t code[]={0xffff0101,66,DST(3,0,15),69,DST(3,1,15),SRC(3,0),
        70,DST(3,2,15),SRC(3,0),1,DST(0,0,15),SRC(3,1),
        1,DST(0,0,2),REG(3,2),0xffff};
    VSProg *program=vs_compile(code,sizeof code/4);assert(program);char source[65536];
    assert(ps_to_msl(program,52,source,sizeof source));vs_free(program);metal_register_ps(52,source);assert(g_psfn[52]);
    NSString *vertex=@"vertex VOut legacy_vertex(uint vid [[vertex_id]]) { VOut o={}; float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)}; o.pos=float4(p[vid],0,1); o.uv0=float4(.5); o.fog=1; return o; }";
    NSError *error=nil;id<MTLLibrary> library=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:vertex] options:nil error:&error];assert(library);
    MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[library newFunctionWithName:@"legacy_vertex"];pd.fragmentFunction=g_psfn[52];pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
    id<MTLRenderPipelineState> pipeline=[g_dev newRenderPipelineStateWithDescriptor:pd error:&error];assert(pipeline);
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;
    id<MTLTexture> input=[g_dev newTextureWithDescriptor:td];float color[4]={.375,.625,.875,.125};[input replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:color bytesPerRow:16];
    td.width=td.height=4;id<MTLTexture> lut=[g_dev newTextureWithDescriptor:td];float values[16][4];
    for(int i=0;i<16;i++){for(int c=0;c<3;c++)values[i][c]=i/16.f;values[i][3]=1;}
    [lut replaceRegion:MTLRegionMake2D(0,0,4,4) mipmapLevel:0 withBytes:values bytesPerRow:64];
    td.width=td.height=1;td.usage=MTLTextureUsageRenderTarget;id<MTLTexture> output=[g_dev newTextureWithDescriptor:td];
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];pass.colorAttachments[0].texture=output;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;
    id<MTLSamplerState> sampler=[g_dev newSamplerStateWithDescriptor:sd];
    id<MTLCommandQueue> queue=[g_dev newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
    struct {float head[8];float c[224][4];float fog[4];int b[16];} constants={0};
    [encoder setRenderPipelineState:pipeline];[encoder setFragmentBytes:&constants length:sizeof constants atIndex:0];
    for(int stage=0;stage<3;stage++){[encoder setFragmentTexture:stage?lut:input atIndex:stage];[encoder setFragmentSamplerState:sampler atIndex:stage];}
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];[command commit];[command waitUntilCompleted];assert(command.status==MTLCommandBufferStatusCompleted);
    float actual[4];[output getBytes:actual bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
    const float expected[4]={.25,.875,.25,1};for(int c=0;c<4;c++)assert(fabsf(actual[c]-expected[c])<1e-5);
}

static void projected_volume(unsigned texture,int sm2){
    int shader=sm2?51:50;
    uint32_t code[]={0xffff0300,
        0x0200001f,0x80070005,DST(1,8,15)|0x00200000u,
        0x0200001f,0xa0000000,DST(10,6,15),
        0x03010042,DST(8,0,15),SRC(1,8),SRC(10,6),0xffff};
    uint32_t pixel2[]={0xffff0200,0x0200001f,0x80000000,DST(3,7,15),
        0x0200001f,0xa0000000,DST(10,4,15),0x03000042,DST(8,0,15),SRC(3,7),SRC(10,4),0xffff};
    VSProg *program=vs_compile(sm2?pixel2:code,sm2?sizeof pixel2/4:sizeof code/4);assert(program);char source[65536];
    assert(ps_to_msl(program,shader,source,sizeof source));vs_free(program);
    metal_register_ps(shader,source);assert(g_psfn[shader]);
    uint32_t vs[]={0xfffe0300,
        0x0200001f,0x80000000,DST(1,0,15),0x0200001f,0x80070005,DST(1,3,15),
        0x0200001f,0x80000000,DST(6,4,15),0x0200001f,0x80070005,DST(6,9,15),
        0x02000001,DST(6,4,15),SRC(1,0),0x02000001,DST(6,9,15),SRC(1,3),0xffff};
    uint32_t vertex2[]={0xfffe0200,0x0200001f,0x80000000,DST(1,0,15),0x0200001f,0x80070005,DST(1,3,15),
        0x02000001,DST(4,0,15),SRC(1,0),0x02000001,DST(6,7,15),SRC(1,3),0xffff};
    program=vs_compile(sm2?vertex2:vs,sm2?sizeof vertex2/4:sizeof vs/4);assert(program);int declaration[16][2];
    for(int i=0;i<16;i++){declaration[i][0]=-1;declaration[i][1]=3;}declaration[0][0]=0;declaration[3][0]=16;
    assert(vs_to_msl(program,shader,declaration,source,sizeof source));vs_free(program);metal_register_vs(shader,source);assert(g_vsfn[shader]);
    NSError *error=nil;
    MTLRenderPipelineDescriptor *pipeline=[MTLRenderPipelineDescriptor new];pipeline.vertexFunction=g_vsfn[shader];pipeline.fragmentFunction=g_psfn[shader];pipeline.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
    id<MTLRenderPipelineState> state=[g_dev newRenderPipelineStateWithDescriptor:pipeline error:&error];
    if(!state)fprintf(stderr,"%s\n",[[error localizedDescription] UTF8String]);assert(state);
    MTLTextureDescriptor *target=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];target.usage=MTLTextureUsageRenderTarget;target.storageMode=MTLStorageModeShared;
    id<MTLTexture> output=[g_dev newTextureWithDescriptor:target];assert(output);
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];pass.colorAttachments[0].texture=output;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    MTLSamplerDescriptor *sampler=[MTLSamplerDescriptor new];sampler.minFilter=sampler.magFilter=MTLSamplerMinMagFilterNearest;sampler.sAddressMode=sampler.tAddressMode=sampler.rAddressMode=MTLSamplerAddressModeClampToEdge;
    id<MTLCommandQueue> queue=[g_dev newCommandQueue];id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
    struct {float head[8];float c[224][4];float fog[4];int b[16];} constants={0};
    float vertices[3][8]={{-1,-1,0,1,.5,1,1.75,2},{3,-1,0,1,.5,1,1.75,2},{-1,3,0,1,.5,1,1.75,2}};
    if(sm2)for(int vertex=0;vertex<3;vertex++)for(int component=4;component<8;component++)vertices[vertex][component]*=.5f;
    struct {unsigned stride,tsel,pad1,pad2;float c[1][4];} vertex_constants={.stride=32};
    id<MTLBuffer> vertex_buffer=[g_dev newBufferWithBytes:vertices length:sizeof vertices options:MTLResourceStorageModeShared];
    [encoder setVertexBuffer:vertex_buffer offset:0 atIndex:1];[encoder setVertexBytes:&vertex_constants length:sizeof vertex_constants atIndex:2];
    [encoder setRenderPipelineState:state];[encoder setFragmentTexture:g_tex[texture] atIndex:sm2?4:6];[encoder setFragmentSamplerState:[g_dev newSamplerStateWithDescriptor:sampler] atIndex:sm2?4:6];[encoder setFragmentBytes:&constants length:sizeof constants atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];[command commit];[command waitUntilCompleted];assert(command.status==MTLCommandBufferStatusCompleted);
    float actual[4];[output getBytes:actual bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
    for(int component=0;component<3;component++)assert(fabsf(actual[component]-57.f/255.f)<1e-5f);
    assert(fabsf(actual[3]-1.f)<1e-5f);
}

static void npot_bc3(unsigned width,unsigned height,unsigned levels){
    const unsigned format=0x35545844u;
    unsigned texture=metal_create_texture(width,height,levels,format);assert(texture);
    assert(g_tex[texture].width==width && g_tex[texture].height==height && g_tex[texture].mipmapLevelCount==levels);
    for(unsigned level=0;level<levels;level++){
        unsigned w=width>>level,h=height>>level;if(!w)w=1;if(!h)h=1;
        unsigned pitch=metal_level_pitch(width,level,format),rows=metal_level_rows(height,level,format);
        size_t length=(size_t)pitch*rows,page=(size_t)sysconf(_SC_PAGESIZE),rounded=(length+page-1)&~(page-1);
        void *input=mmap(NULL,rounded+2*page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
        void *output=mmap(NULL,rounded+2*page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(input!=MAP_FAILED && output!=MAP_FAILED);
        assert(!mprotect(input,page,PROT_NONE) && !mprotect((char*)input+page+rounded,page,PROT_NONE));
        assert(!mprotect(output,page,PROT_NONE) && !mprotect((char*)output+page+rounded,page,PROT_NONE));
        uint8_t *source=(uint8_t*)input+page+rounded-length,*result=(uint8_t*)output+page+rounded-length;
        for(size_t byte=0;byte<length;byte++)source[byte]=(uint8_t)(byte*17+level);
        long uploads=metal_tex_uploaded();metal_upload_texture(texture,level,source,pitch,width,height,format);
        assert(metal_tex_uploaded()==uploads+1);
        [g_tex[texture] getBytes:result bytesPerRow:pitch fromRegion:MTLRegionMake2D(0,0,w,h) mipmapLevel:level];
        assert(!memcmp(source,result,length));
        munmap(input,rounded+2*page);munmap(output,rounded+2*page);
    }
    assert(g_tex_lvlmask[texture]==(1u<<levels)-1);
}

static void reorder_dependencies(void){
    setenv("HD_REORDER","1",1);setenv("PASSMERGE","1",1);
    MDraw draws[3]={0};draws[1].target=42;draws[1].first=1;draws[2].first=2;draws[2].stage_tex[6]=42;
    g_dbuf[0]=draws;g_dn[0]=3;pass_reorder(0);
    assert(draws[1].first==1 && draws[2].first==2);
    draws[2].stage_tex[6]=0;pass_reorder(0);
    assert(draws[1].first==2 && draws[2].first==1);
    g_dbuf[0]=NULL;g_dn[0]=0;
}

int main(int argc,char **argv){
    if(argc==2 && !strcmp(argv[1],"--prelude")){fputs(kPrelude.UTF8String,stdout);return 0;}
    if((argc==3 || argc==4) && (!strcmp(argv[1],"--depth") || !strcmp(argv[1],"--depth-mrt"))){
        @autoreleasepool {
            g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;
            NSString *source=[NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[2]] encoding:NSUTF8StringEncoding error:nil];assert(source);
            if([source hasPrefix:kPrelude])source=[source substringFromIndex:kPrelude.length];
            if(!strcmp(argv[1],"--depth-mrt"))metal_set_ps_outputs(1,argc==4?(unsigned)atoi(argv[3]):3);
            metal_register_ps(1,source.UTF8String);return !g_psfn[1] || !metal_depth_fragment(1);
        }
    }
    reorder_dependencies();
    @autoreleasepool {
        g_dev=MTLCreateSystemDefaultDevice(); if(!g_dev)return 77;
        if(argc==2&&!strcmp(argv[1],"--fixed-road-copy")){rain_fixed_function_reference(NULL);return 0;}
        if(argc==3&&!strcmp(argv[1],"--rain-vertices")){rain_fixed_function_reference(argv[2]);return 0;}
        depth_bias_reference();rain_fixed_function_reference(NULL);
        legacy_color_remap();
        npot_bc3(758,1200,11);npot_bc3(1600,2262,12);
        unsigned tex=metal_create_texture_volume(4,4,4,3,21);
        assert(tex && g_tex[tex].textureType==MTLTextureType3D && g_tex[tex].mipmapLevelCount==3);
        uint32_t pixels[64];for(int i=0;i<64;i++)pixels[i]=0xff000000u|(i*0x010101u);
        assert(metal_upload_texture_volume(tex,0,pixels,16,64));
        uint32_t readback[64]={0};
        [g_tex[tex] getBytes:readback bytesPerRow:16 bytesPerImage:64 fromRegion:MTLRegionMake3D(0,0,0,4,4,4) mipmapLevel:0 slice:0];
        assert(!memcmp(pixels,readback,sizeof pixels));
        projected_volume(tex,0);projected_volume(tex,1);
        unsigned luminance=metal_create_texture_volume(4,4,4,1,50);assert(luminance);
        assert(!metal_create_texture_volume(4,4,4,1,41));
        assert(!metal_create_texture(4,4,1,41));
        uint8_t brightness[64];for(int i=0;i<64;i++)brightness[i]=i;
        assert(metal_upload_texture_volume(luminance,0,brightness,4,16));projected_volume(luminance,0);
        assert(!metal_create_texture_volume(0,4,4,1,21));
        assert(!metal_upload_texture_volume(tex,3,pixels,16,64));
        assert(!metal_upload_texture_volume(tex,0,pixels,1,4));
        unsigned textures[16]={0},samplers[16]={0}; textures[6]=tex;samplers[6]=1234;
        metal_set_stage_textures(textures);metal_set_samplers(samplers);
        assert(g_cur_stage_tex[6]==tex && g_cur_smp[6]==1234);
        float constants[224][4]={{0}};int booleans[16]={0};constants[223][3]=.75f;booleans[15]=1;
        metal_set_ps(1,&constants[0][0]);metal_set_ps_bool(booleans);
        assert(g_cur_psc[223][3]==.75f && g_cur_psbool[15]==1);
        g_vbuf[0]=calloc(3,sizeof(MVert));g_dbuf[0]=calloc(2,sizeof(MDraw));g_pscb[0]=calloc(2,sizeof(PSConstants));
        metal_set_depth_bias(-.01f,2);
        int types[16]={0};types[6]=4;metal_set_ps_model(50,0x0300,types);metal_set_ps(50,&constants[0][0]);
        TVert triangle[3]={0};metal_set_fixed_function(1);metal_draw_tv(triangle,3,4,0);metal_set_fixed_function(0);
        assert(g_dbuf[0][0].fixed_function==1);
        assert(g_dn[0]==1 && g_dbuf[0][0].stage_tex[6]==tex && g_dbuf[0][0].smp[6]==1234);
        assert(g_dbuf[0][0].depth_bias==-.01f && g_dbuf[0][0].slope_bias==2);
        assert(g_pscb[0][0].c[223][3]==.75f && g_pscb[0][0].b[15]==1);
        textures[6]=0;samplers[6]=4321;booleans[15]=0;constants[223][3]=.1f;
        metal_set_stage_textures(textures);metal_set_samplers(samplers);metal_set_ps_bool(booleans);metal_set_ps(50,&constants[0][0]);
        metal_set_depth_bias(0,0);assert(g_dbuf[0][0].depth_bias==-.01f && g_dbuf[0][0].slope_bias==2);
        assert(g_dbuf[0][0].stage_tex[6]==tex && g_dbuf[0][0].smp[6]==1234 && g_pscb[0][0].b[15]==1 && g_pscb[0][0].c[223][3]==.75f);
        g_kbuf[0]=malloc(4096);metal_set_depth_bias(.1f,-3);
        MDraw *raw=raw_rec(0,32,0,50,&constants[0][0],1);assert(raw && raw->depth_bias==.1f && raw->slope_bias==-3);
        free(g_kbuf[0]);
        free(g_vbuf[0]);free(g_dbuf[0]);free(g_pscb[0]);
        puts("PASS: backend volume texture upload, stage6, c223, b15");
    }
}
