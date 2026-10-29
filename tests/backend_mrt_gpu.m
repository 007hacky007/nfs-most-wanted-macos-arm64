/* Ordered target snapshots and the production Metal color attachments. */
#include "../runtime/metal.m"
#include <assert.h>
int g_perflog; _Atomic int g_pl_thumb_req; char g_pl_dir[900]; _Atomic long g_mw_dump_frame;
int g_texrep_frame_on; __strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX]; uint8_t g_texrep_k[TEXREP_MAXTEX];
int com_frees(void){return 0;}

int main(void){ @autoreleasepool {
    g_dbuf[0]=calloc(MAXD,sizeof(MDraw)); g_vbuf[0]=calloc(MAXV,sizeof(MVert));
    g_pscb[0]=calloc(MAXD,sizeof(PSConstants));
    TVert vertices[3]={0};
    for(unsigned i=0;i<3;i++){vertices[i].x=i==1?3:-1; vertices[i].y=i==2?3:-1; vertices[i].w=1;}
    metal_set_render_target(7); metal_set_render_target_at(1,8);
    metal_draw_tv(vertices,3,4,0);
    metal_set_color_write(1,1);
    metal_set_render_target_at(1,9); metal_clear_target(0xff204060);
    metal_set_color_write(1,2);
    metal_set_render_target_at(1,0); metal_draw_tv(vertices,3,4,0);
    assert(g_dn[0]==3 && g_dbuf[0][0].mrt[0]==8 && g_dbuf[0][1].mrt[0]==9 && !g_dbuf[0][2].mrt[0]);
    assert(g_dbuf[0][0].mrt_write==0xfff && g_dbuf[0][1].mrt_write==0xff1 && g_dbuf[0][2].mrt_write==0xff2);
    assert(!color_targets_equal(&g_dbuf[0][0],&g_dbuf[0][1]));
    metal_set_render_target_at(1,9); metal_reset_rts();
    metal_draw_tv(vertices,3,4,0); assert(!g_dbuf[0][3].mrt[0] && g_dbuf[0][3].mrt_write==0xfff);
    MDraw saved[4];memcpy(saved,g_dbuf[0],sizeof saved);
    memset(g_dbuf[0],0,sizeof saved);g_dn[0]=2;g_dbuf[0][1].mrt[0]=8;
    assert(hd_ms_predict(0,0)==1 && hd_ms_memless_ok(0,0));
    memcpy(g_dbuf[0],saved,sizeof saved);g_dn[0]=4;
    g_dev=MTLCreateSystemDefaultDevice(); if(!g_dev)return 77;
    g_queue=[g_dev newCommandQueue];
    for(unsigned t=7;t<=9;t++){
        MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:4 height:4 mipmapped:NO];
        td.storageMode=MTLStorageModeShared; td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
        g_tex[t]=[g_dev newTextureWithDescriptor:td]; assert(g_tex[t]);
    }
    NSError *error=nil;
    g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:&error]; assert(g_lib);
    NSString *source=@"vertex VOut mrt_vertex(uint vid [[vertex_id]]) { VOut o={}; float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};o.pos=float4(p[vid],0,1);return o;}\nstruct MRT {float4 c0 [[color(0)]],c1 [[color(1)]];};fragment MRT ps_1(VOut i [[stage_in]]) {return {float4(1,0,0,1),float4(0,1,0,1)};}";
    id<MTLLibrary> lib=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:source] options:nil error:&error]; assert(lib);
    g_vsfn[1]=[lib newFunctionWithName:@"mrt_vertex"]; g_psfn[1]=[lib newFunctionWithName:@"ps_1"]; metal_set_ps_outputs(1,3);
    unsigned char touched[MAXTEX+1]={0}; int screen_touched=0;
    for(unsigned i=0;i<2;i++){
        MDraw *draw=&g_dbuf[0][i];
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];
        color_pass_attachments(pass,draw,nil,touched,screen_touched);
        assert(pass.colorAttachments[0].texture==g_tex[7]); assert(pass.colorAttachments[1].texture==g_tex[8+i]);
        assert(pass.colorAttachments[0].loadAction==MTLLoadActionClear);
        MTLPixelFormat formats[4]; for(unsigned n=0;n<4;n++)formats[n]=pass.colorAttachments[n].texture.pixelFormat;
        id<MTLCommandBuffer> cb=[g_queue commandBuffer]; id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:pass];
        if(!draw->is_clear){
            uint64_t key=metal_shader_key(1,1)|(15u<<14)|color_write_key(draw->mrt_write);
            id<MTLRenderPipelineState> pso=pso_for_colors(key,formats); assert(pso);
            [enc setRenderPipelineState:pso]; [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        }
        [enc endEncoding]; [cb commit]; [cb waitUntilCompleted]; assert(cb.status==MTLCommandBufferStatusCompleted);
        color_pass_mark_touched(draw,touched,&screen_touched);
        uint8_t pixel[4];
        [g_tex[7] getBytes:pixel bytesPerRow:4 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
        if(i)assert(pixel[0]==0x60&&pixel[1]==0x40&&pixel[2]==0x20&&pixel[3]==255);
        else assert(pixel[0]==0&&pixel[1]==0&&pixel[2]==255&&pixel[3]==255);
        [g_tex[8+i] getBytes:pixel bytesPerRow:4 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
        if(i)assert(pixel[0]==0x60&&pixel[1]==0x40&&pixel[2]==0x20&&pixel[3]==255);
        else assert(pixel[0]==0&&pixel[1]==255&&pixel[2]==0&&pixel[3]==255);
    }
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];
    color_pass_attachments(pass,&g_dbuf[0][2],nil,touched,screen_touched);
    assert(!pass.colorAttachments[1].texture&&pass.colorAttachments[0].loadAction==MTLLoadActionLoad);
    /* Changing only a secondary format or mask must select a new pipeline. */
    MTLPixelFormat formats[4]={MTLPixelFormatBGRA8Unorm,MTLPixelFormatBGRA8Unorm,0,0};
    uint64_t key=metal_shader_key(1,1)|(15u<<14)|color_write_key(0xfff);
    id<MTLRenderPipelineState> original=pso_for_colors(key,formats); assert(original);
    formats[1]=MTLPixelFormatRGBA8Unorm;
    id<MTLRenderPipelineState> changed=pso_for_colors(key,formats); assert(changed&&changed!=original);
    assert(pso_for_colors(key,formats)==changed);
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:formats[1] width:4 height:4 mipmapped:NO];
    td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget;
    id<MTLTexture> output=[g_dev newTextureWithDescriptor:td];
    pass=[MTLRenderPassDescriptor new];pass.colorAttachments[0].texture=g_tex[7];pass.colorAttachments[1].texture=output;
    for(unsigned n=0;n<2;n++){pass.colorAttachments[n].loadAction=MTLLoadActionClear;pass.colorAttachments[n].storeAction=MTLStoreActionStore;pass.colorAttachments[n].clearColor=MTLClearColorMake(.25,.25,.25,.25);}
    /* The shader writes green to target1; a red-only mask keeps its prior GBA. */
    key=metal_shader_key(1,1)|(15u<<14)|color_write_key(g_dbuf[0][1].mrt_write);
    id<MTLRenderPipelineState> masked=pso_for_colors(key,formats);assert(masked&&masked!=changed);
    id<MTLCommandBuffer> cb=[g_queue commandBuffer];id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:pass];
    [enc setRenderPipelineState:masked];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];[cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);
    uint8_t pixel[4];[output getBytes:pixel bytesPerRow:4 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
    assert(pixel[0]==0&&pixel[1]==64&&pixel[2]==64&&pixel[3]==64);
    /* A screen MRT consumer needs the preceding multisampled image resolved. */
    NSString *blue=@"fragment float4 ps_2(VOut i [[stage_in]]) {return float4(0,0,1,1);}";
    lib=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:blue] options:nil error:&error];assert(lib);
    g_psfn[2]=[lib newFunctionWithName:@"ps_2"];
    td.pixelFormat=MTLPixelFormatBGRA8Unorm;td.textureType=MTLTextureType2DMultisample;td.sampleCount=4;td.storageMode=MTLStorageModePrivate;
    id<MTLTexture> multisample=[g_dev newTextureWithDescriptor:td];assert(multisample);
    pass=[MTLRenderPassDescriptor new];pass.colorAttachments[0].texture=multisample;pass.colorAttachments[0].resolveTexture=g_tex[7];
    pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionUnknown;
    formats[1]=0;key=metal_shader_key(2,1)|(15u<<14)|(1ull<<48)|(2ull<<50);
    cb=[g_queue commandBuffer];enc=[cb renderCommandEncoderWithDescriptor:pass];
    [enc setRenderPipelineState:pso_for_colors(key,formats)];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    memset(g_dbuf[0],0,sizeof saved);g_dn[0]=2;g_dbuf[0][1].mrt[0]=8;
    g_hd_msp.on=1;g_hd_msp.ml=0;g_hd_msp.dz=0;
    assert(hd_ms_end(enc,0,1,1,0,hd_ms_predict(0,0))==0);
    [enc endEncoding];[cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);
    [g_tex[7] getBytes:pixel bytesPerRow:4 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
    assert(pixel[0]==255&&pixel[1]==0&&pixel[2]==0&&pixel[3]==255);
    puts("queued MRT outputs, target switches, unbind, Reset and ordered clears passed");
} return 0; }
