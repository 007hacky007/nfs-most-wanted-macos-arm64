#include "vsemu.h"
#ifdef __OBJC__
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <unistd.h>
#endif
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REG(t,n) (0x80000000u | (((t)&7u)<<28) | (((t)&24u)<<8) | (n))
#define DST(t,n,m) (REG(t,n)|((m)<<16))
#define SRC(t,n) (REG(t,n)|0x00e40000u)

static void semantic_cpu(void) {
    uint32_t code[] = {0xfffe0300,
        0x0200001f,0x80000000,DST(1,0,15),
        0x0200001f,0x8000000a,DST(1,2,15),
        0x0200001f,0x80000005,DST(1,3,15),
        0x0200001f,0x80000000,DST(6,4,15),
        0x0200001f,0x80070005,DST(6,9,15),
        0x0200001f,0x8005000a,DST(6,2,15),
        0x02000001,DST(6,4,15),SRC(1,0),
        0x02000001,DST(6,9,15),SRC(1,3),
        0x02000001,DST(6,2,15),SRC(1,2),0xffff};
    VSProg *p=vs_compile(code,sizeof code/4); assert(p);
    VSConst k={0}; float in[16][4]={{2,3,4,1},{0},{0.2f,0.3f,0.4f,0.5f},{5,6,7,8}}; VSOut o;
    assert(vs_run(p,&k,in,&o));
    assert(o.pos[0]==2 && o.pos[3]==1);
    assert(o.tex[7][0]==5 && o.tex[7][3]==8);
    assert(o.col[5][0]==.2f && o.col[5][3]==.5f);
    char out[65536]; int decl[16][2]; for(int i=0;i<16;i++){decl[i][0]=-1;decl[i][1]=3;}
    assert(vs_to_msl(p,7,decl,out,sizeof out));
    assert(strstr(out,"O.uv7") && strstr(out,"O.col5"));
    vs_free(p);
}

static void pixel_semantics_flow(void) {
    uint32_t code[]={0xffff0300,
        0x0200001f,0x80070005,DST(1,8,15)|0x00200000u,
        0x0200001f,0x90000000,DST(10,6,15),
        0x01000028,SRC(14,1),
        0x03000042,DST(0,2,15),SRC(1,8),SRC(10,6),
        0x0000002a,
        0x02000001,DST(0,2,15),SRC(2,35),
        0x0000002b,
        0x0200005b,DST(0,3,15),SRC(0,2),
        0x01000041,DST(0,3,15),
        0x02000001,DST(8,0,15),SRC(0,2),0xffff};
    VSProg*p=vs_compile(code,sizeof code/4);assert(p);
    char out[65536]; assert(ps_to_msl(p,8,out,sizeof out));
    assert(strstr(out,"v[8] = i.uv7"));
    assert(strstr(out,"float4 uv7 [[centroid_perspective]]"));
    assert(strstr(out,"s6.sample(sm6") && strstr(out,"P.c[35]"));
    assert(strstr(out,"if (") && strstr(out,"P.b[0].y") && strstr(out,"} else {"));
    assert(strstr(out,"dfdx(r[2])") && strstr(out,"(r[3]).xyz < 0.0"));
    assert(!strstr(out,"saturate(i.col0)") && !strstr(out,"res.rgb = mix(P.fog"));
    vs_free(p);
}

static void cpu_bool_flow(void){
    uint32_t code[]={0xfffe0300,0x0200001f,0x80000000,DST(6,0,15),
        0x01000028,SRC(14,0),0x02000001,DST(6,0,15),SRC(2,0),
        0x0000002a,0x02000001,DST(6,0,15),SRC(2,1),0x0000002b,0xffff};
    VSProg*p=vs_compile(code,sizeof code/4);assert(p);VSConst k={0};VSOut o;float input[16][4]={{0}};
    k.f[0][0]=1;k.f[1][0]=5;
    for(int value=0;value<2;value++){k.b[0]=value;assert(vs_run(p,&k,input,&o));assert(o.pos[0]==(value?1:5));}
    vs_free(p);
}

static void texture_controls(void){
    uint32_t code[]={0xffff0300,0x0200001f,0x80000005,DST(1,0,15),
        0x0200001f,0x90000000,DST(10,6,15),
        0x03010042,DST(0,0,15),SRC(1,0),SRC(10,6),
        0x03020042,DST(8,0,15),SRC(1,0),SRC(10,6),0xffff};
    VSProg*p=vs_compile(code,sizeof code/4);assert(p);char out[65536];assert(ps_to_msl(p,10,out,sizeof out));
    assert(strstr(out,".xy / (v[0]).w") && strstr(out,"bias((v[0]).w)"));vs_free(p);
}

static void sm2_higher_sampler_and_coordinate(void){
    uint32_t code[]={0xffff0200,0x0200001f,0x80000000,DST(3,7,15),
        0x0200001f,0x90000000,DST(10,4,15),
        0x03000042,DST(8,0,15),SRC(3,7),SRC(10,4),0xffff};
    VSProg*p=vs_compile(code,sizeof code/4);assert(p);char out[65536];assert(ps_to_msl(p,10,out,sizeof out));
    assert(strstr(out,"#define SMP4(") && strstr(out,"s4 [[texture(4)]]") && strstr(out,"sm4 [[sampler(4)]]"));
    assert(strstr(out,"t[7] = i.uv7") && strstr(out,"SMP4((t[7]).xy"));vs_free(p);
}

static void pixel_color_outputs(void){
    uint32_t code[]={0xffff0200,
        0x02000001,DST(8,0,15),SRC(2,0),
        0x02000001,DST(8,1,15),SRC(2,1),
        0x02000001,DST(8,2,5),SRC(2,2),
        0x02000001,DST(8,3,10),SRC(2,3),0xffff};
    VSProg*p=vs_compile(code,sizeof code/4);assert(p);char out[65536];
    assert(ps_color_output_mask(p)==15);
    assert(ps_to_msl(p,42,out,sizeof out));
    assert(strstr(out,"oC1 = (P.c[1])") && strstr(out,"oC2.xz") && strstr(out,"oC3.yw"));
    assert(strstr(out,"c0 [[color(0)]]") && strstr(out,"c1 [[color(1)]]") &&
           strstr(out,"c2 [[color(2)]]") && strstr(out,"c3 [[color(3)]]"));
    assert(strstr(out,"float4 res = oC;") && strstr(out,"if (res.a < P.aref)"));
    vs_free(p);
    code[0]=0xffff0300;p=vs_compile(code,sizeof code/4);assert(p);
    assert(ps_color_output_mask(p)==15 && ps_to_msl(p,42,out,sizeof out));vs_free(p);
    uint32_t sparse[]={0xffff0200,0x02000001,DST(8,0,15),SRC(2,0),
        0x02000001,DST(8,2,15),SRC(2,1),0xffff};
    p=vs_compile(sparse,sizeof sparse/4);assert(p);assert(ps_color_output_mask(p)==5);
    assert(ps_to_msl(p,43,out,sizeof out));
    assert(strstr(out,"c2 [[color(2)]]") && !strstr(out,"c1 [[color(1)]]"));vs_free(p);
    sparse[5]=DST(8,4,15);p=vs_compile(sparse,sizeof sparse/4);assert(p);
    assert(!ps_color_output_mask(p) && !ps_to_msl(p,43,out,sizeof out));vs_free(p);
    uint32_t legacy[]={0xffff0101,1,DST(0,0,15),SRC(2,0),0xffff};
    p=vs_compile(legacy,sizeof legacy/4);assert(p);assert(ps_color_output_mask(p)==1);
    assert(ps_to_msl(p,43,out,sizeof out) && !strstr(out,"PSMRT_"));vs_free(p);
}

static void unsupported_rejected(void) {
    uint32_t code[]={0xffff0300,0x01000019,SRC(18,0),0xffff};
    VSProg*p=vs_compile(code,sizeof code/4);assert(p); char out[65536];
    assert(!ps_to_msl(p,9,out,sizeof out));vs_free(p);
    uint32_t malformed[]={0xffff0300,0x0000002a,0xffff};
    p=vs_compile(malformed,sizeof malformed/4);
    assert(!p || !ps_to_msl(p,9,out,sizeof out));vs_free(p);
    uint32_t missing[]={0xffff0300,0x01000001,DST(8,0,15),0xffff};
    p=vs_compile(missing,sizeof missing/4);assert(!p || !ps_to_msl(p,9,out,sizeof out));vs_free(p);
    uint32_t undefined[]={0xffff0300,0x02000001,DST(8,0,15),SRC(1,8),0xffff};
    p=vs_compile(undefined,sizeof undefined/4);assert(!p || !ps_to_msl(p,9,out,sizeof out));vs_free(p);
}

#ifdef __OBJC__
static const char *metal_header =
    "#include <metal_stdlib>\nusing namespace metal;\n"
    "struct VOut { float4 pos [[position]]; float4 col0,col1,col2,col3,col4,col5;"
    " float4 uv0,uv1,uv2,uv3,uv4,uv5,uv6,uv7; float fog; };\n"
    "struct PSPar { float aref,usec,pad0,pad1; float4 proj; float4 c[224]; float4 fog; int4 b[4]; };\n";

static int gpu_color_outputs(const char *path){
    alarm(15);
    @autoreleasepool {
        id<MTLDevice>device=MTLCreateSystemDefaultDevice();if(!device)return 77;
        uint32_t code[]={0xffff0200,0x02000001,DST(8,0,15),SRC(2,0),
            0x02000001,DST(8,1,15),SRC(2,1),0x02000001,DST(8,2,5),SRC(2,2),
            0x02000001,DST(8,3,10),SRC(2,3),0xffff};
        uint32_t *tokens=code;size_t count=sizeof code/4;
        if(path){FILE*f=fopen(path,"rb");assert(f);fseek(f,0,SEEK_END);count=(size_t)ftell(f)/4;rewind(f);tokens=malloc(count*4);assert(fread(tokens,4,count,f)==count);fclose(f);}
        for(unsigned model=0;model<(path?1u:2u);model++){
            if(!path)code[0]=model?0xffff0300:0xffff0200;
            VSProg*p=vs_compile(tokens,count);assert(p);unsigned mask=ps_color_output_mask(p);assert(mask==(path?3u:15u));
            char msl[65536];assert(ps_to_msl(p,42,msl,sizeof msl));vs_free(p);
            NSString*vertex=@"\nvertex VOut mrt_vertex(uint n [[vertex_id]]){VOut o={};o.pos=float4(n==1?3:-1,n==2?3:-1,0,1);o.uv0=float4(.5,.5,0,1);o.fog=1;return o;}\n";
            NSString*source=[[[NSString stringWithUTF8String:metal_header] stringByAppendingString:[NSString stringWithUTF8String:msl]] stringByAppendingString:vertex];
            NSError*error=nil;id<MTLLibrary>lib=[device newLibraryWithSource:source options:nil error:&error];
            if(!lib){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 1;}
            MTLRenderPipelineDescriptor*pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"mrt_vertex"];pd.fragmentFunction=[lib newFunctionWithName:@"ps_42"];
            unsigned targets=path?2:4;for(unsigned t=0;t<targets;t++)pd.colorAttachments[t].pixelFormat=MTLPixelFormatRGBA32Float;
            id<MTLRenderPipelineState>pipeline=[device newRenderPipelineStateWithDescriptor:pd error:&error];assert(pipeline);
            MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:2 height:2 mipmapped:NO];td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
            id<MTLTexture>output[4];for(unsigned t=0;t<targets;t++)output[t]=[device newTextureWithDescriptor:td];
            td.width=td.height=1;id<MTLTexture>input=[device newTextureWithDescriptor:td];float sample[]={.25,.5,.75,.25};[input replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:sample bytesPerRow:16];
            MTLSamplerDescriptor*sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;id<MTLSamplerState>sampler=[device newSamplerStateWithDescriptor:sd];
            struct{float head[8];float c[224][4],fog[4];int b[16];}constants={0};
            const float values[4][4]={{.2,.3,.4,.25},{.7,.6,.5,.9},{.11,.22,.33,.44},{.15,.25,.35,.45}};memcpy(constants.c,values,sizeof values);
            constants.c[16][0]=.2;constants.c[16][1]=.6;constants.c[16][2]=.2;
            const float expected[4][4]={{.2,.3,.4,.25},{.7,.6,.5,.9},{.11,0,.33,0},{0,.25,0,.45}};
            const float hdr[2][4]={{.25,.5,.75,.5},{.1875,.375,.5625,.25}};
            id<MTLCommandQueue>queue=[device newCommandQueue];
            for(unsigned discard=0;discard<2;discard++){
                constants.head[0]=path?(discard?.6:.3):(discard?.5:0);
                MTLRenderPassDescriptor*pass=[MTLRenderPassDescriptor new];for(unsigned t=0;t<targets;t++){pass.colorAttachments[t].texture=output[t];pass.colorAttachments[t].loadAction=MTLLoadActionClear;pass.colorAttachments[t].storeAction=MTLStoreActionStore;pass.colorAttachments[t].clearColor=MTLClearColorMake(0,0,0,0);}
                id<MTLCommandBuffer>command=[queue commandBuffer];id<MTLRenderCommandEncoder>encoder=[command renderCommandEncoderWithDescriptor:pass];
                [encoder setRenderPipelineState:pipeline];[encoder setFragmentBytes:&constants length:sizeof constants atIndex:0];[encoder setFragmentTexture:input atIndex:0];[encoder setFragmentSamplerState:sampler atIndex:0];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];[command commit];[command waitUntilCompleted];assert(command.status==MTLCommandBufferStatusCompleted);
                for(unsigned t=0;t<targets;t++){float actual[16];[output[t] getBytes:actual bytesPerRow:32 fromRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0];for(unsigned i=0;i<16;i++){float want=discard?0:path?hdr[t][i%4]:expected[t][i%4];if(fabsf(actual[i]-want)>1e-5){fprintf(stderr,"MRT target%u component%u %g != %g\n",t,i,actual[i],want);return 1;}}}
            }
        }
        if(path)free(tokens);puts("PASS: independent MRT colors and alpha-test color0 reference");return 0;
    }
}

static int gpu_reference(void){
    @autoreleasepool {
        id<MTLDevice> device=MTLCreateSystemDefaultDevice();
        if(!device)return 77;
        uint32_t pixel[]={0xffff0300,
            0x0200001f,0x80070005,DST(1,8,15),
            0x01000028,SRC(14,1),
            0x03000005,DST(0,0,15),SRC(1,8),SRC(2,35),
            0x0000002a,
            0x03000002,DST(0,0,15),SRC(1,8),SRC(2,35),
            0x0000002b,
            0x03000002,DST(0,0,6),SRC(0,0),SRC(2,36),
            0x04000012,DST(8,0,15),SRC(2,38),SRC(0,0),SRC(2,39),0xffff};
        VSProg *p=vs_compile(pixel,sizeof pixel/4); assert(p);
        char msl[65536];assert(ps_to_msl(p,50,msl,sizeof msl));vs_free(p);
        NSString *source=[NSString stringWithUTF8String:msl];
        NSRange signature=[source rangeOfString:@") {\n"];
        assert(signature.location!=NSNotFound);
        source=[@"kernel void reference(device float4 *result [[buffer(0)]], constant PSPar &P [[buffer(1)]]) {\n VOut i; i.uv7=float4(2.0,3.0,4.0,1.0);\n" stringByAppendingString:[source substringFromIndex:NSMaxRange(signature)]];
        source=[source stringByReplacingOccurrencesOfString:@"  if (res.a < P.aref) discard_fragment();\n" withString:@""];
        source=[source stringByReplacingOccurrencesOfString:@"  return res;" withString:@"  result[0]=res;"];
        source=[[NSString stringWithUTF8String:metal_header] stringByAppendingString:source];
        NSError *error=nil;
        id<MTLLibrary> library=[device newLibraryWithSource:source options:nil error:&error];
        if(!library){fprintf(stderr,"%s\n",[[error localizedDescription] UTF8String]);return 1;}
        id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"reference"] error:&error];assert(pipeline);
        struct {float head[8];float c[224][4];float fog[4];int b[16];} constants={0};
        float c35[]={.25f,.5f,.75f,1}, c36[]={1,2,3,4};
        memcpy(constants.c[35],c35,sizeof c35);memcpy(constants.c[36],c36,sizeof c36);
        for(int j=0;j<4;j++){constants.c[38][j]=.25f;constants.c[39][j]=.8f;}
        id<MTLBuffer> result=[device newBufferWithLength:16 options:MTLResourceStorageModeShared];
        id<MTLCommandQueue> queue=[device newCommandQueue];
        float input[]={2,3,4,1};
        for(int branch=0;branch<2;branch++){
            constants.b[1]=branch;
            id<MTLCommandBuffer> command=[queue commandBuffer];
            id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
            [encoder setComputePipelineState:pipeline];[encoder setBuffer:result offset:0 atIndex:0];
            [encoder setBytes:&constants length:sizeof constants atIndex:1];
            [encoder dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
            [encoder endEncoding];[command commit];[command waitUntilCompleted];
            assert(command.status==MTLCommandBufferStatusCompleted);
            float *actual=result.contents;
            for(int j=0;j<4;j++){
                float expected=branch ? input[j]*c35[j] : input[j]+c35[j];
                if(j==1 || j==2)expected+=c36[j];
                expected=.25f*expected+.75f*.8f;
                if(fabsf(actual[j]-expected)>1e-5f){fprintf(stderr,"GPU component %d: %g != %g\n",j,actual[j],expected);return 1;}
            }
        }
    }
    puts("PASS: GPU SM3 semantic inputs, constants, masked arithmetic and both bool branches");return 0;
}
#endif

int main(int argc,char**argv){
#ifdef __OBJC__
    if(argc==2 && !strcmp(argv[1],"--gpu"))return gpu_reference();
    if(argc==2 && !strcmp(argv[1],"--gpu-mrt"))return gpu_color_outputs(NULL);
    if(argc==3 && !strcmp(argv[1],"--gpu-hdr-mrt"))return gpu_color_outputs(argv[2]);
    if(argc==3 && !strcmp(argv[1],"--metal")){
        @autoreleasepool {
            id<MTLDevice> device=MTLCreateSystemDefaultDevice();
            if(!device){fprintf(stderr,"Metal device unavailable\n");return 77;}
            NSError *error=nil;
            NSString *source=[NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[2]] encoding:NSUTF8StringEncoding error:&error];
            id<MTLLibrary> library=[device newLibraryWithSource:source options:nil error:&error];
            if(!library){fprintf(stderr,"%s\n",[[error localizedDescription] UTF8String]);return 1;}
            return 0;
        }
    }
#endif
    if(argc==2){
        FILE*f=fopen(argv[1],"rb");assert(f);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);
        uint32_t*t=malloc(n);assert(fread(t,1,n,f)==(size_t)n);fclose(f);
        VSProg*p=vs_compile(t,n/4);assert(p);char*out=malloc(262144);int len;
        if((t[0]>>16)==0xffff)len=ps_to_msl(p,1,out,262144);
        else{int decl[16][2];for(int i=0;i<16;i++){decl[i][0]=i*16;decl[i][1]=3;}len=vs_to_msl(p,1,decl,out,262144);}
        if(!len)return 2;fputs(out,stdout);vs_free(p);free(t);free(out);return 0;
    }
    semantic_cpu();pixel_semantics_flow();cpu_bool_flow();texture_controls();sm2_higher_sampler_and_coordinate();pixel_color_outputs();unsupported_rejected();puts("PASS: SM3 semantics, constants, samplers, flow and rejection");
}
