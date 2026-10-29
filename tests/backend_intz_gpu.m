/* INTZ aliases the exact depth surface written by the production encoder. */
#include "../runtime/metal.m"
#include <assert.h>
int g_perflog;_Atomic int g_pl_thumb_req;char g_pl_dir[900];_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;__strong id<MTLTexture>g_texrep_tex[TEXREP_MAXTEX];uint8_t g_texrep_k[TEXREP_MAXTEX];
static int samples=1;
int com_frees(void){return 1;}
int enh_msaa_samples(int*autop){if(autop)*autop=0;return samples;}
int hfr_mailbox(void){return 0;}
void guest_wait_begin(void){}void guest_wait_end(void){}
void texrep_main_frame(id<MTLCommandQueue>queue){(void)queue;}
void texrep_released(unsigned texture){(void)texture;}
int fpscounter_on(void){return 0;}
void fpscounter_note_gpu(double value){(void)value;}
void fpscounter_note_present(void){}void fpscounter_note_presented(double value){(void)value;}
void hfr_note_present_call(void){}void hfr_note_presented(double value){(void)value;}
double hfr_present_min_duration(void){return 0;}
@interface INTZFailDevice:NSObject
@end
@implementation INTZFailDevice
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor*)descriptor{(void)descriptor;return nil;}
@end
static id<MTLTexture>screen;
static void wait_gpu(void){id<MTLCommandBuffer>cb=[g_queue commandBuffer];[cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);}
static void frame(void){
 metal_present();assert(g_ready>=0);struct timespec now;clock_gettime(CLOCK_MONOTONIC,&now);
 metal_encode_ready(screen,nil,now,now);wait_gpu();rt_free_pending();
}
static void check_color(id<MTLTexture>texture,unsigned value){
 unsigned width=(unsigned)texture.width,height=(unsigned)texture.height,pitch=(width*4+255)&~255u;
 id<MTLBuffer>buffer=[g_dev newBufferWithLength:pitch*height options:MTLResourceStorageModeShared];
 id<MTLCommandBuffer>cb=[g_queue commandBuffer];id<MTLBlitCommandEncoder>blit=[cb blitCommandEncoder];
 [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(width,height,1) toBuffer:buffer destinationOffset:0 destinationBytesPerRow:pitch destinationBytesPerImage:pitch*height];
 [blit endEncoding];[cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);
 for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++){
  uint8_t*p=(uint8_t*)buffer.contents+y*pitch+x*4;
  if(p[0]!=value||p[1]!=value||p[2]!=value||p[3]!=255)fprintf(stderr,"INTZ pixel got %u/%u/%u/%u expected %u\n",p[0],p[1],p[2],p[3],value);
  assert(p[0]==value&&p[1]==value&&p[2]==value&&p[3]==255);
 }
}
static void draw(unsigned ps,unsigned vs){
 metal_set_ps(ps,NULL);TVert v[3]={0};for(unsigned i=0;i<3;i++)v[i].w=1;
 metal_draw_tv(v,3,4,0);g_dbuf[g_cur][g_dn[g_cur]-1].vsid=vs;g_rvn[g_cur]=g_kn[g_cur]=16;
}
static void sample(unsigned texture){
 metal_set_zsurf(0);metal_set_depth(0);unsigned stages[16]={0};stages[4]=texture;metal_set_stage_textures(stages);draw(2,1);
}
static void write_depth(unsigned zid,unsigned vs){
 unsigned stages[16]={0};metal_set_stage_textures(stages);metal_set_zsurf(zid);metal_set_depth(11);
 metal_clear_target_ex(0xff000000,3,1);draw(1,vs);
}
int main(int argc,char**argv){@autoreleasepool{
 if(argc==2&&!strcmp(argv[1],"msaa"))samples=4;
 setenv("PASSMERGE","1",1);g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;
 if(![g_dev supportsTextureSampleCount:samples])return 77;g_queue=[g_dev newCommandQueue];
 g_layer=[CAMetalLayer layer];g_layer.device=g_dev;g_hd_msn=samples;
 MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:8 height:8 mipmapped:NO];td.storageMode=MTLStorageModePrivate;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;screen=[g_dev newTextureWithDescriptor:td];assert(screen);
 for(unsigned b=0;b<2;b++){g_dbuf[b]=calloc(MAXD,sizeof(MDraw));g_vbuf[b]=calloc(MAXV,sizeof(MVert));g_pscb[b]=calloc(MAXD,sizeof(PSConstants));g_rvbuf[b]=calloc(1,MAXRV);g_kbuf[b]=calloc(1,MAXKB);}
 g_fb_sem=dispatch_semaphore_create(NFB);g_cur_blend=15u<<14;g_cur_cull=1;
 NSError*error=nil;g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:&error];assert(g_lib);
 NSString*source=@"vertex VOut intz_vertex(uint i [[vertex_id]]) { VOut o={};float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};o.pos=float4(p[i],.25,1);return o;}fragment float4 ps_1(VOut i [[stage_in]]) {return float4(1,0,0,1);}fragment float4 ps_2(VOut i [[stage_in]],texture2d<float> depth [[texture(4)]]) {constexpr sampler sm(coord::normalized,address::clamp_to_edge,filter::nearest);float z=depth.sample(sm,i.pos.xy/8.0).r;return float4(z,z,z,1);}";
 id<MTLLibrary>lib=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:source] options:nil error:&error];assert(lib);
 g_vsfn[1]=[lib newFunctionWithName:@"intz_vertex"];g_psfn[1]=[lib newFunctionWithName:@"ps_1"];g_psfn[2]=[lib newFunctionWithName:@"ps_2"];
 lib=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:[source stringByReplacingOccurrencesOfString:@".25,1" withString:@".75,1"]] options:nil error:&error];assert(lib);g_vsfn[2]=[lib newFunctionWithName:@"intz_vertex"];
 int types[16]={0};types[4]=2;metal_set_ps_model(2,0x0200,types);
 MTLPixelFormat colors[4]={MTLPixelFormatBGRA8Unorm,0,0,0};g_pso=pso_for_colors(metal_shader_key(1,1)|(15u<<14),colors);assert(g_pso);
 unsigned before=g_texn;assert(!metal_create_depth_texture(0,8,2));assert(!metal_create_depth_texture(8,8193,2));assert(!metal_create_depth_texture(8,8,1));assert(!metal_create_depth_texture(8,8,64));assert(g_texn==before);
 id<MTLDevice>device=g_dev;g_dev=(id<MTLDevice>)[INTZFailDevice new];assert(!metal_create_depth_texture(8,8,5));g_dev=device;assert(g_texn==before&&!g_ztex[5]);
 unsigned texture=metal_create_depth_texture(8,8,2);assert(texture&&g_tex[texture]==g_ztex[2]);
 assert(g_tex[texture].pixelFormat==MTLPixelFormatDepth32Float&&g_tex[texture].storageMode==MTLStorageModePrivate);
 assert((g_tex[texture].usage&(MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget))==(MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget));
 metal_set_render_target(0);sample(texture);frame();check_color(screen,255);
 /* A later screen draw must not hide a clear from an earlier offscreen reader. */
 unsigned offscreen=metal_create_texture_ex(8,8,1,21,1);assert(offscreen);
 metal_set_zsurf(2);metal_set_depth(11);metal_clear_target_ex(0,2,.5);
 metal_set_render_target(offscreen);sample(texture);
 metal_set_render_target(0);draw(1,1);frame();check_color(g_tex[offscreen],128);
 /* No intervening geometry: the explicit clear must be visible to sampling. */
 metal_set_zsurf(2);metal_set_depth(11);metal_clear_target_ex(0,2,.5);sample(texture);frame();check_color(screen,128);
 unsigned long long passes=atomic_load(&g_pass_n);write_depth(2,1);sample(texture);frame();check_color(screen,64);assert(atomic_load(&g_pass_n)==passes+2);assert(g_tex[texture]==g_ztex[2]);
 write_depth(2,2);sample(texture);frame();check_color(screen,191);
 /* A smaller explicit surface must not silently resize or lose its alias. */
 unsigned small=metal_create_depth_texture(4,4,3);assert(small);id<MTLTexture>small_alias=g_tex[small];unsigned long long mismatch=atomic_load(&g_z_mismatch);
 write_depth(3,1);sample(small);frame();check_color(screen,255);assert(g_ztex[3]==small_alias&&atomic_load(&g_z_mismatch)>mismatch);
 /* Old delayed frees and Reset sweeps may not clear a newer alias. */
 metal_free_texture(small);unsigned replacement=metal_create_depth_texture(4,4,3);assert(replacement&&replacement!=small);id<MTLTexture>new_alias=g_tex[replacement];
 for(unsigned i=0;i<3;i++){frame();if(i<2)assert(g_tex[small]);}
 assert(!g_tex[small]&&g_ztex[3]==new_alias);
 metal_free_texture(replacement);for(unsigned i=0;i<3;i++)frame();assert(!g_tex[replacement]&&!g_ztex[3]);
 metal_reset_rts();metal_reset_rts();unsigned fresh=metal_create_depth_texture(8,8,2);assert(fresh);id<MTLTexture>fresh_alias=g_tex[fresh];metal_free_texture(texture);
 for(unsigned i=0;i<3;i++)frame();assert(!g_tex[texture]&&g_ztex[2]==fresh_alias&&g_tex[fresh]==fresh_alias);
 assert(!atomic_load(&g_cb_err));puts("INTZ queue: initial/clear/depth sampler4, alias mismatch, MSAA and deferred lifetime passed");
}return 0;}
