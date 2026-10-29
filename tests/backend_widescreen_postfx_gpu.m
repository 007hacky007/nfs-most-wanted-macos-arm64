#include "../runtime/metal.m"
#include <assert.h>
int g_perflog;_Atomic int g_pl_thumb_req;char g_pl_dir[900];_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;__strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX];uint8_t g_texrep_k[TEXREP_MAXTEX];
static id<MTLTexture> texture(unsigned w,unsigned h){
 MTLTextureDescriptor*d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:w height:h mipmapped:NO];d.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;d.storageMode=MTLStorageModeShared;return[g_dev newTextureWithDescriptor:d];
}
static float gamma_cpu(float x,unsigned mode){
 if(mode==2){double z=fmax(0,fmin(x,1));return z+z*(1-z)*(-.184189+1.668233*z-3.0067*z*z+1.694186*z*z*z);}
 double z=fmax(x,0),blend=fmin(1,z*6.56649+.311465);return .541901*z*(1-blend)+pow(z,1.13465)*(1-exp2(-13.53054*z))*blend;
}
static void finish(id<MTLCommandBuffer>cb){[cb commit];[cb waitUntilCompleted];if(cb.error)fprintf(stderr,"%s\n",cb.error.description.UTF8String);assert(cb.status==MTLCommandBufferStatusCompleted);}
static void reset(void){ws_postfx_release_frame(0);g_dn[0]=g_vn[0]=g_pscn[0]=0;}
static void apply(id<MTLTexture>screen,unsigned source,unsigned gamma,unsigned border){
 metal_widescreen_postfx(source,gamma,border);unsigned i=g_dn[0]-1;assert(g_dbuf[0][i].is_blit==2);
 id<MTLCommandBuffer>cb=[g_queue commandBuffer];assert(ws_postfx_encode(cb,screen,g_ws_sources[0][i],&g_dbuf[0][i],nil,i));finish(cb);reset();
}
static void pixels(void){
 const unsigned W=1600,H=1000;size_t bytes=W*H*16;float *input=malloc(bytes),*output=malloc(bytes);assert(input&&output);
 for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){unsigned i=(y*W+x)*4;input[i]=(float)x/(W-1);input[i+1]=(float)y/(H-1);input[i+2]=.03125;input[i+3]=.25;}
 id<MTLTexture>screen=texture(W,H);assert(screen);
 for(unsigned gamma=0;gamma<=2;gamma++)for(unsigned border=0;border<=2;border++){
  if(!gamma&&!border)continue;[screen replaceRegion:MTLRegionMake2D(0,0,W,H) mipmapLevel:0 withBytes:input bytesPerRow:W*16];
  apply(screen,0,gamma,border);[screen getBytes:output bytesPerRow:W*16 fromRegion:MTLRegionMake2D(0,0,W,H) mipmapLevel:0];
  for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){
   int edge=border&&(x==0||y==0||(border==2&&(x==W-1||y==H-1)));unsigned i=(y*W+x)*4;
   for(unsigned c=0;c<4;c++){float expected=edge?(c==3?1:0):c==3?(gamma?1:input[i+c]):gamma?gamma_cpu(input[i+c],gamma):input[i+c];
    if(fabsf(output[i+c]-expected)>1e-5){fprintf(stderr,"pixel g%u b%u %u,%u c%u %.9g != %.9g\n",gamma,border,x,y,c,output[i+c],expected);abort();}}
  }
 }
 /* The active offscreen target gets the clears; gamma alone writes BB. */
 id<MTLTexture>off=texture(32,32);g_tex[1]=off;g_texn=2;
 float small[32*32*4];for(unsigned i=0;i<32*32;i++){small[i*4]=.5;small[i*4+1]=.25;small[i*4+2]=.75;small[i*4+3]=.125;}
 [off replaceRegion:MTLRegionMake2D(0,0,32,32) mipmapLevel:0 withBytes:small bytesPerRow:32*16];
 [screen replaceRegion:MTLRegionMake2D(0,0,W,H) mipmapLevel:0 withBytes:input bytesPerRow:W*16];
 apply(screen,1,0,2);[screen getBytes:output bytesPerRow:W*16 fromRegion:MTLRegionMake2D(0,0,W,H) mipmapLevel:0];assert(!memcmp(input,output,bytes));
 [off getBytes:small bytesPerRow:32*16 fromRegion:MTLRegionMake2D(0,0,32,32) mipmapLevel:0];assert(small[0]==0&&small[(31*32+31)*4]==.5);
 apply(screen,1,1,0);[screen getBytes:output bytesPerRow:W*16 fromRegion:MTLRegionMake2D(0,0,W,H) mipmapLevel:0];assert(fabsf(output[(500*W+800)*4]-gamma_cpu(.5,1))<1e-5);
 free(input);free(output);
}
static void query_and_lifetime(void){
 id<MTLTexture>screen=texture(8,8),source=texture(8,8);g_tex[2]=source;g_texn=3;
 float data[8*8*4];for(unsigned i=0;i<8*8*4;i++)data[i]=.5;[source replaceRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0 withBytes:data bytesPerRow:128];
 unsigned q=metal_query_create();assert(q&&!metal_query_issue(q,2));metal_widescreen_postfx(2,1,2);assert(!metal_query_issue(q,1));
 assert(g_ws_sources[0][0]==source);g_tex[2]=nil;source=nil;assert(g_ws_sources[0][0]);
 MQSubmission*s=mq_capture(0);id<MTLBuffer>b=mq_buffer(s);assert(s&&b);id<MTLCommandBuffer>cb=[g_queue commandBuffer];
 assert(ws_postfx_encode(cb,screen,g_ws_sources[0][0],&g_dbuf[0][0],b,0));reset();assert(!g_ws_sources[0][0]);finish(cb);mq_complete(s,b.contents,1);
 uint32_t result=0;assert(!metal_query_get_data(q,0,&result)&&result==64);metal_query_destroy(q);
 q=metal_query_create();assert(!metal_query_issue(q,2));metal_widescreen_postfx(0,0,2);assert(!g_dbuf[0][0].query_mask);assert(!metal_query_issue(q,1));
 s=mq_capture(0);b=mq_buffer(s);cb=[g_queue commandBuffer];assert(ws_postfx_encode(cb,screen,nil,&g_dbuf[0][0],b,0));finish(cb);mq_complete(s,b.contents,1);
 assert(!metal_query_get_data(q,0,&result)&&result==0);metal_query_destroy(q);reset();
 /* Draw/marker/draw order survives pass optimization; source stays retained. */
 g_dn[0]=4;memset(g_dbuf[0],0,4*sizeof(MDraw));g_dbuf[0][1].target=1;g_dbuf[0][2].target=0;
 metal_widescreen_postfx(1,1,0);MDraw before=g_dbuf[0][4];pass_reorder(0);assert(!memcmp(&before,&g_dbuf[0][4],sizeof before));reset();
 /* Disabled and malformed settings never allocate a command. */
 metal_widescreen_postfx(0,0,0);metal_widescreen_postfx(0,3,1);assert(!g_dn[0]);
}
static void ordered_and_resolved(void){
 id<MTLTexture>screen=texture(8,8);float data[256];for(unsigned i=0;i<256;i++)data[i]=.5;
 [screen replaceRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0 withBytes:data bytesPerRow:128];
 metal_widescreen_postfx(0,1,2);id<MTLCommandBuffer>cb=[g_queue commandBuffer];
 assert(ws_postfx_encode(cb,screen,nil,&g_dbuf[0][0],nil,0));
 /* A later draw stays after gamma and can overwrite the AA border. */
 NSString*src=@"#include <metal_stdlib>\nusing namespace metal; vertex float4 v(uint n [[vertex_id]]){return float4(n==1?3:-1,n==2?3:-1,0,1);} fragment float4 f(){return float4(.5,.25,.75,.125);}";
 NSError*error=nil;id<MTLLibrary>lib=[g_dev newLibraryWithSource:src options:nil error:&error];assert(lib);
 MTLRenderPipelineDescriptor*pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"v"];pd.fragmentFunction=[lib newFunctionWithName:@"f"];pd.colorAttachments[0].pixelFormat=screen.pixelFormat;
 id<MTLRenderPipelineState>pipeline=[g_dev newRenderPipelineStateWithDescriptor:pd error:&error];assert(pipeline);
 MTLRenderPassDescriptor*rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=screen;rp.colorAttachments[0].loadAction=MTLLoadActionLoad;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
 id<MTLRenderCommandEncoder>enc=[cb renderCommandEncoderWithDescriptor:rp];[enc setRenderPipelineState:pipeline];[enc setScissorRect:(MTLScissorRect){0,0,1,1}];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];finish(cb);reset();
 [screen getBytes:data bytesPerRow:128 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];assert(data[0]==.5&&data[3]==.125&&data[4]==0&&fabsf(data[(3*8+3)*4]-gamma_cpu(.5,1))<1e-5);
 /* Bound cube faces retain their selected slice across the postfx command. */
 MTLTextureDescriptor*ct=[MTLTextureDescriptor textureCubeDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float size:8 mipmapped:NO];ct.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;ct.storageMode=MTLStorageModeShared;
 id<MTLTexture>cube=[g_dev newTextureWithDescriptor:ct];assert(cube);for(unsigned i=0;i<256;i++)data[i]=.5;
 for(unsigned face=0;face<6;face++)[cube replaceRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0 slice:face withBytes:data bytesPerRow:128 bytesPerImage:1024];
 MDraw cube_draw={0};cube_draw.blit_src=5|(4u<<16);cube_draw.ws_border=2;
 cb=[g_queue commandBuffer];assert(ws_postfx_encode(cb,screen,cube,&cube_draw,nil,0));finish(cb);
 for(unsigned face=0;face<6;face++){[cube getBytes:data bytesPerRow:128 bytesPerImage:1024 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0 slice:face];assert(data[0]==(face==3?0:.5));assert(data[(3*8+3)*4]==.5);}
 /* A real MSAA source is resolved before the shader reads it. */
 if([g_dev supportsTextureSampleCount:4]){
  MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA16Float width:8 height:8 mipmapped:NO];td.textureType=MTLTextureType2DMultisample;td.sampleCount=4;td.storageMode=MTLStorageModePrivate;td.usage=MTLTextureUsageRenderTarget;
  id<MTLTexture>ms=[g_dev newTextureWithDescriptor:td];assert(ms);cb=[g_queue commandBuffer];rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=ms;rp.colorAttachments[0].loadAction=MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;rp.colorAttachments[0].clearColor=MTLClearColorMake(.5,.25,.75,.5);
  enc=[cb renderCommandEncoderWithDescriptor:rp];[enc endEncoding];MDraw draw={0};draw.blit_src=1;draw.ws_gamma=1;draw.ws_border=2;
  assert(ws_postfx_encode(cb,screen,ms,&draw,nil,0));finish(cb);[screen getBytes:data bytesPerRow:128 fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];assert(data[0]==0&&fabsf(data[(3*8+3)*4]-gamma_cpu(.5,1))<1e-5);
 }
}

static void format_conversion(void){
 id<MTLTexture>source=texture(256,1);MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:256 height:1 mipmapped:NO];td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;td.storageMode=MTLStorageModeShared;id<MTLTexture>screen=[g_dev newTextureWithDescriptor:td];assert(screen);
 float data[1024];unsigned char actual[1024];for(unsigned i=0;i<256;i++)for(unsigned c=0;c<4;c++)data[4*i+c]=(i+.49f)/255.f;
 [source replaceRegion:MTLRegionMake2D(0,0,256,1) mipmapLevel:0 withBytes:data bytesPerRow:sizeof data];
 MDraw draw={0};draw.blit_src=1;draw.ws_gamma=1;id<MTLCommandBuffer>cb=[g_queue commandBuffer];assert(ws_postfx_encode(cb,screen,source,&draw,nil,0));finish(cb);
 [screen getBytes:actual bytesPerRow:sizeof actual fromRegion:MTLRegionMake2D(0,0,256,1) mipmapLevel:0];
 unsigned bad=0;for(unsigned i=0;i<256;i++){unsigned expected=(unsigned)lroundf(gamma_cpu((float)i/255.f,1)*255);if(actual[4*i]!=expected)bad++;}
 if(bad)fprintf(stderr,"gamma input format conversion: %u mismatched pixels\n",bad);assert(!bad);
}

static void binary_reference(const char *path,unsigned mode){
 NSString*ref=[NSString stringWithContentsOfFile:[NSString stringWithUTF8String:path] encoding:NSUTF8StringEncoding error:nil];assert(ref);
 NSString *vs=@"vertex PSIn_1 ref_vertex(uint n [[vertex_id]]){PSIn_1 o={};o.pos=float4(n==1?3:-1,n==2?3:-1,0,1);o.uv0=float4(n==1?2:0,n==2?-1:1,0,0);return o;}\n";
 NSString*source=[[kPrelude stringByAppendingString:ref]stringByAppendingString:vs];NSError*err=nil;
 id<MTLLibrary>lib=[g_dev newLibraryWithSource:source options:nil error:&err];if(!lib)fprintf(stderr,"%s\n",err.description.UTF8String);assert(lib);
 MTLRenderPipelineDescriptor*pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"ref_vertex"];pd.fragmentFunction=[lib newFunctionWithName:@"ps_1"];pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
 id<MTLRenderPipelineState>pipeline=[g_dev newRenderPipelineStateWithDescriptor:pd error:&err];assert(pipeline);
 unsigned W=4096;float *data=malloc(W*16),*expected=malloc(W*16),*actual=malloc(W*16);for(unsigned x=0;x<W;x++){data[4*x]=(float)x/(W-1);data[4*x+1]=1-data[4*x];data[4*x+2]=.0125;data[4*x+3]=.5;}
 id<MTLTexture>input=texture(W,1),out=texture(W,1);[input replaceRegion:MTLRegionMake2D(0,0,W,1) mipmapLevel:0 withBytes:data bytesPerRow:W*16];
 MTLSamplerDescriptor*sd=[MTLSamplerDescriptor new];sd.minFilter=sd.magFilter=MTLSamplerMinMagFilterNearest;id<MTLSamplerState>sm=[g_dev newSamplerStateWithDescriptor:sd];
 id<MTLCommandBuffer>cb=[g_queue commandBuffer];MTLRenderPassDescriptor*rp=[MTLRenderPassDescriptor new];rp.colorAttachments[0].texture=out;rp.colorAttachments[0].loadAction=MTLLoadActionDontCare;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
 id<MTLRenderCommandEncoder>enc=[cb renderCommandEncoderWithDescriptor:rp];[enc setRenderPipelineState:pipeline];[enc setFragmentTexture:input atIndex:0];[enc setFragmentSamplerState:sm atIndex:0];unsigned zero[924]={0};[enc setFragmentBytes:zero length:sizeof zero atIndex:0];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];finish(cb);
 [out getBytes:expected bytesPerRow:W*16 fromRegion:MTLRegionMake2D(0,0,W,1) mipmapLevel:0];apply(input,0,mode,0);[input getBytes:actual bytesPerRow:W*16 fromRegion:MTLRegionMake2D(0,0,W,1) mipmapLevel:0];
 for(unsigned i=0;i<W*4;i++){if(fabsf(actual[i]-expected[i])>1e-5){fprintf(stderr,"binary vector%u: %g != %g\n",i,actual[i],expected[i]);abort();}}free(data);free(expected);free(actual);
}
int main(int argc,char**argv){@autoreleasepool{
 g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;g_queue=[g_dev newCommandQueue];g_dbuf[0]=calloc(MAXD,sizeof(MDraw));g_vbuf[0]=calloc(MAXV,sizeof(MVert));g_pscb[0]=calloc(MAXD,sizeof(PSConstants));
 assert(g_dbuf[0]&&g_vbuf[0]&&g_pscb[0]);if(argc>1)binary_reference(argv[1],1);if(argc>2)binary_reference(argv[2],2);pixels();query_and_lifetime();ordered_and_resolved();format_conversion();
 puts("WS postfx: binary gamma vectors, physical1600x1000 borders, source targets, queries and lifetime passed");
 }return 0;}
