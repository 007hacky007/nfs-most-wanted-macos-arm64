/* Synthetic loading UI and alpha-test variants exercise the production renderer. */
#include "../runtime/metal.m"
#include <assert.h>
int g_perflog; _Atomic int g_pl_thumb_req; char g_pl_dir[900]; _Atomic long g_mw_dump_frame;
int g_texrep_frame_on; __strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX]; uint8_t g_texrep_k[TEXREP_MAXTEX];
int com_frees(void){ return 0; }
void loading_show(NSView *);
void loading_update(void);
void loading_frame_presented(int);

static void shader_test(void){
 g_dev=MTLCreateSystemDefaultDevice(); if(!g_dev)exit(77);
 const char *source="fragment float4 ps_1(VOut i [[stage_in]], constant PSPar &P [[buffer(0)]]) { float4 res=float4(1,0,0,.25); if (res.a < P.aref) discard_fragment(); return res; }";
 metal_register_ps(1,source); assert(g_psfn[1]);
 metal_register_ps(2,"fragment float4 ps_2(VOut i [[stage_in]], constant PSPar &P [[buffer(0)]]) { float4 res=float4(1,0,0,.25); if (res.a < P.aref) discard_fragment(); return res; }");
 assert(g_psfn[1]==g_psfn[2]); /* Identical programs share one Metal compilation. */
 /* Creating a shader must not compile the unused variant a second time. */
 assert(!g_psfn_nd[1]);
 MTLPixelFormat colors[4]={MTLPixelFormatBGRA8Unorm,0,0,0};
 g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:NULL];assert(g_lib);
 NSString *vertex=@"vertex VOut loading_vertex(uint i [[vertex_id]]) { VOut o={};float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};o.pos=float4(p[i],.25,1);return o;}";
 id<MTLLibrary> library=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:vertex] options:nil error:NULL];assert(library);
 g_vsfn[1]=[library newFunctionWithName:@"loading_vertex"];
 uint64_t base=metal_shader_key(1,1)|(15u<<14);
 assert(pso_for_colors(base,colors)); assert(!g_psfn_nd[1]);
 assert(pso_for_colors(base|(1ull<<52),colors)); assert(g_psfn_nd[1]);
 assert(g_psfn_nd[1]!=g_psfn[1]);
 id<MTLFunction> cached=g_psfn_nd[1];
 assert(pso_for_colors(base|(1ull<<52),colors)); assert(g_psfn_nd[1]==cached);
 g_queue=[g_dev newCommandQueue];
 MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:colors[0] width:4 height:4 mipmapped:NO];
 td.usage=MTLTextureUsageRenderTarget;td.storageMode=MTLStorageModeShared;
 id<MTLTexture> color=[g_dev newTextureWithDescriptor:td];
 td.pixelFormat=MTLPixelFormatDepth32Float;td.storageMode=MTLStorageModePrivate;
 id<MTLTexture> depth=[g_dev newTextureWithDescriptor:td];
 for(int nd=0;nd<2;nd++){
  MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor new];
  pass.colorAttachments[0].texture=color;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
  pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(0,0,0,1);
  pass.depthAttachment.texture=depth;pass.depthAttachment.loadAction=MTLLoadActionClear;
  id<MTLCommandBuffer> cb=[g_queue commandBuffer];id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:pass];
  [enc setRenderPipelineState:pso_for_colors(base|((uint64_t)nd<<52),colors)];
  float params[944]={.5};[enc setFragmentBytes:params length:sizeof params atIndex:0];
  [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];
  [cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);
  uint32_t pixels[16];[color getBytes:pixels bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,4,4) mipmapLevel:0];
  for(int i=0;i<16;i++)assert(pixels[i]==(nd?0x40ff0000u:0xff000000u));
 }
 puts("unused alpha variants stay deferred and compile once when requested");
}
static void ui_test(const char *capture){
 [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
 NSWindow *window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,800,500) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
 [window orderBack:nil];NSView *root=window.contentView;
 loading_show(root);loading_update();assert(root.subviews.count==1);
 NSView *overlay=root.subviews[0];assert(!overlay.hidden);
 loading_frame_presented(0);loading_update();assert(overlay.superview==root);
 atomic_store(&g_loading_shaders,42);
 loading_update();[window setContentSize:NSMakeSize(900,560)];
 assert([g_loading_status.stringValue containsString:@"42 shaders"]);
 [root layoutSubtreeIfNeeded];assert(NSEqualSizes(overlay.frame.size,root.bounds.size));
 for(int i=0;i<10;i++)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.05]];
 NSBitmapImageRep *rep=[root bitmapImageRepForCachingDisplayInRect:root.bounds];
 [root cacheDisplayInRect:root.bounds toBitmapImageRep:rep];
 [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:@(capture) atomically:YES];
 loading_frame_presented(1);loading_update();assert(!overlay.superview);
 loading_show(root);assert(root.subviews.count==0); /* A late update cannot resurrect startup UI. */
 [window orderOut:nil];puts("loading UI survives a blank frame and resize, and hides after content");
}
int main(int argc,char **argv){@autoreleasepool{
 if(argc>1&&!strcmp(argv[1],"ui"))ui_test(argv[2]);else shader_test();
}return 0;}
