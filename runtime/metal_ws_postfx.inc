/* September 2026 WidescreenFix, dbe2c0eb9030: PostFX and MSAA callbacks.
 * MIT license: see third_party/WidescreenFix-LICENSE.
 * Ordered with game draws; the separate source reference survives Release
 * and frame replacement. D3D Clear borders precede the gamma draw. */
static id<MTLTexture> g_ws_sources[2][MAXD];
static void ws_postfx_release_frame(int b){
    for(unsigned i=0;i<g_dn[b];i++)if(g_dbuf[b][i].is_blit==2)g_ws_sources[b][i]=nil;
}
void metal_widescreen_postfx(unsigned source,unsigned gamma,unsigned border){
    if((!gamma&&!border)||gamma>2||border>2)return;
    pthread_mutex_lock(&g_qlock);int b=g_cur;unsigned id_=TGT_ID(source);
    if(!g_dbuf[b]||g_dn[b]>=MAXD || (source&&(!id_||id_>=MAXTEX||!g_tex[id_]))){
        mq_fail_active();pthread_mutex_unlock(&g_qlock);return;
    }
    unsigned i=g_dn[b]++;MDraw *d=&g_dbuf[b][i];memset(d,0,sizeof *d);
    d->is_blit=2;d->blit_src=source;d->target=gamma?0:source;
    d->ws_gamma=gamma;d->ws_border=border;d->query_mask=gamma?mq_snapshot(b):0;
    g_ws_sources[b][i]=source?g_tex[id_]:nil;
    pthread_mutex_unlock(&g_qlock);
}
static NSString *kWSPostFXSource=@
"#include <metal_stdlib>\nusing namespace metal;\n"
"struct WSOut{float4 pos [[position]];};\n"
"vertex WSOut ws_vertex(uint n [[vertex_id]]){float2 p=float2(n==1?3:-1,n==2?3:-1);return {float4(p,0,1)};}\n"
"struct WSParam{uint gamma,border,width,height;};\n"
"float ws_gamma(float x,uint mode){if(mode==2){x=saturate(x);float x2=x*x,x3=x2*x;"
"float p=-.184189+1.668233*x-3.0067*x2+1.694186*x3;return x+x*(1-x)*p;}"
"x=max(0.0f,x);float a=.541901*x,b=pow(x,1.13465f)*(1-exp2(-13.53054*x));"
"return mix(a,b,saturate(x*6.56649+.311465));}\n"
"fragment float4 ws_gamma_pixel(WSOut i [[stage_in]],texture2d<float> src [[texture(0)]],constant WSParam &p [[buffer(0)]]){"
"constexpr sampler sm(coord::normalized,address::clamp_to_edge,filter::nearest);"
"float3 c=src.sample(sm,i.pos.xy/float2(p.width,p.height)).rgb;"
"return float4(ws_gamma(c.r,p.gamma),ws_gamma(c.g,p.gamma),ws_gamma(c.b,p.gamma),1);}\n"
"fragment float4 ws_copy_pixel(WSOut i [[stage_in]],texture2d<float> src [[texture(0)]],constant WSParam &p [[buffer(0)]]){"
"constexpr sampler sm(coord::normalized,address::clamp_to_edge,filter::nearest);return src.sample(sm,i.pos.xy/float2(p.width,p.height));}\n"
"fragment float4 ws_border_pixel(WSOut i [[stage_in]],constant WSParam &p [[buffer(0)]]){"
"float2 q=i.pos.xy;bool edge=(q.x<p.width&&q.y<1)||(q.x<1&&q.y<p.height);"
"if(p.border==2)edge=edge||(q.x<p.width&&q.y>=p.height-1&&q.y<p.height+5)||(q.x>=p.width-1&&q.x<p.width+5&&q.y<p.height+5);"
"if(!edge)discard_fragment();return float4(0,0,0,1);}\n";
static id<MTLLibrary> g_ws_library;
static NSMutableDictionary<NSNumber*,id<MTLRenderPipelineState>> *g_ws_pipelines;
static id<MTLTexture> g_ws_scratch,g_ws_resolve;
static id<MTLRenderPipelineState> ws_postfx_pipeline(id<MTLTexture> target,unsigned kind){
    NSError *error=nil;
    if(!g_ws_library)g_ws_library=[g_dev newLibraryWithSource:kWSPostFXSource options:nil error:&error];
    if(!g_ws_library)return nil;
    if(!g_ws_pipelines)g_ws_pipelines=[NSMutableDictionary new];
    NSNumber *key=@(((unsigned long long)target.pixelFormat<<8)|(target.sampleCount<<2)|kind);
    id<MTLRenderPipelineState> pipeline=g_ws_pipelines[key];
    if(!pipeline){
        MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];
        pd.vertexFunction=[g_ws_library newFunctionWithName:@"ws_vertex"];
        pd.fragmentFunction=[g_ws_library newFunctionWithName:kind==1?@"ws_border_pixel":kind==2?@"ws_copy_pixel":@"ws_gamma_pixel"];
        pd.colorAttachments[0].pixelFormat=target.pixelFormat;pd.rasterSampleCount=target.sampleCount;
        pipeline=[g_dev newRenderPipelineStateWithDescriptor:pd error:&error];
        if(pipeline)g_ws_pipelines[key]=pipeline;
    }
    return pipeline;
}
static id<MTLTexture> ws_postfx_scratch(id<MTLTexture> old,id<MTLTexture> model){
    if(old&&old.width==model.width&&old.height==model.height&&old.pixelFormat==model.pixelFormat)return old;
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:model.pixelFormat width:model.width height:model.height mipmapped:NO];
    td.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;td.storageMode=MTLStorageModePrivate;
    return [g_dev newTextureWithDescriptor:td];
}
static int ws_postfx_encode(id<MTLCommandBuffer> cb,id<MTLTexture> backbuffer,id<MTLTexture> saved_source,
                           const MDraw *draw,id<MTLBuffer> queries,unsigned index){
    id<MTLTexture> source=draw->blit_src?saved_source:backbuffer;
    if(!source||!backbuffer)return 0;
    unsigned face=TGT_FACE(draw->blit_src);
    if(face){
        if(source.textureType!=MTLTextureTypeCube||face>6)return 0;
        source=[source newTextureViewWithPixelFormat:source.pixelFormat textureType:MTLTextureType2D levels:NSMakeRange(0,1) slices:NSMakeRange(face-1,1)];
        if(!source)return 0;
    }
    struct {unsigned gamma,border,width,height;} p={draw->ws_gamma,draw->ws_border,(unsigned)backbuffer.width,(unsigned)backbuffer.height};
    if(draw->ws_border){
        id<MTLRenderPipelineState> pipeline=ws_postfx_pipeline(source,1);if(!pipeline)return 0;
        MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=source;
        rp.colorAttachments[0].loadAction=MTLLoadActionLoad;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
        id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:rp];if(!enc)return 0;
        [enc setRenderPipelineState:pipeline];[enc setFragmentBytes:&p length:sizeof p atIndex:0];
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];
    }
    if(!draw->ws_gamma)return 1;
    id<MTLRenderPipelineState> pipeline=ws_postfx_pipeline(backbuffer,0);if(!pipeline)return 0;
    g_ws_scratch=ws_postfx_scratch(g_ws_scratch,backbuffer);
    if(!g_ws_scratch)return 0;
    if(source.sampleCount>1){
        g_ws_resolve=ws_postfx_scratch(g_ws_resolve,source);if(!g_ws_resolve)return 0;
        MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=source;
        rp.colorAttachments[0].resolveTexture=g_ws_resolve;rp.colorAttachments[0].loadAction=MTLLoadActionLoad;
        rp.colorAttachments[0].storeAction=MTLStoreActionStoreAndMultisampleResolve;
        id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:rp];if(!enc)return 0;[enc endEncoding];
        source=g_ws_resolve;
    }
    if(source.width==g_ws_scratch.width&&source.height==g_ws_scratch.height&&source.pixelFormat==g_ws_scratch.pixelFormat){
        id<MTLBlitCommandEncoder> copy=[cb blitCommandEncoder];if(!copy)return 0;
        [copy copyFromTexture:source sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                    sourceSize:MTLSizeMake(source.width,source.height,1) toTexture:g_ws_scratch destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
        [copy endEncoding];
    }else{
        /* Upstream's point StretchRect converts into a BB-sized, BB-format
         * scene texture before gamma, including UNORM quantization. */
        id<MTLRenderPipelineState> copy_pipeline=ws_postfx_pipeline(g_ws_scratch,2);if(!copy_pipeline)return 0;
        MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=g_ws_scratch;
        rp.colorAttachments[0].loadAction=MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
        id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:rp];if(!enc)return 0;
        [enc setRenderPipelineState:copy_pipeline];[enc setFragmentTexture:source atIndex:0];
        [enc setFragmentBytes:&p length:sizeof p atIndex:0];
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];
    }
    MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=backbuffer;
    rp.colorAttachments[0].loadAction=MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
    rp.visibilityResultBuffer=queries;
    id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:rp];if(!enc)return 0;
    [enc setRenderPipelineState:pipeline];[enc setFragmentTexture:g_ws_scratch atIndex:0];
    [enc setFragmentBytes:&p length:sizeof p atIndex:0];mq_encode(enc,queries,draw,index);
    [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];return 1;
}
