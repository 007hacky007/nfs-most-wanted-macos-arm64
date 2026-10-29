/* Exercise the production queue consumer without a window or drawable. */
#include "../runtime/metal.m"
#include <assert.h>
#include <unistd.h>
int g_perflog; _Atomic int g_pl_thumb_req; char g_pl_dir[900]; _Atomic long g_mw_dump_frame;
int g_texrep_frame_on; __strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX]; uint8_t g_texrep_k[TEXREP_MAXTEX];
static _Atomic unsigned waits, resumes;
static int test_samples=1,fail_mode;
@interface RBNullQueue : NSObject
@end
@implementation RBNullQueue
- (id<MTLCommandBuffer>)commandBuffer{return nil;}
@end
static unsigned denied_renders,forwarded_blits,forwarded_commits;
@interface RBNoRenderBuffer : NSObject
@property(nonatomic,strong) id<MTLCommandBuffer> backing;
@end
@implementation RBNoRenderBuffer
- (id)forwardingTargetForSelector:(SEL)selector{(void)selector;return self.backing;}
- (id<MTLRenderCommandEncoder>)renderCommandEncoderWithDescriptor:(MTLRenderPassDescriptor*)descriptor{
 (void)descriptor;denied_renders++;return nil;
}
- (id<MTLBlitCommandEncoder>)blitCommandEncoder{forwarded_blits++;return [self.backing blitCommandEncoder];}
- (void)commit{forwarded_commits++;[self.backing commit];}
@end
@interface RBNoRenderQueue : NSObject
@property(nonatomic,strong) id<MTLCommandQueue> backing;
@end
@implementation RBNoRenderQueue
- (id<MTLCommandBuffer>)commandBuffer{
 RBNoRenderBuffer *buffer=[RBNoRenderBuffer new];buffer.backing=[self.backing commandBuffer];
 return (id<MTLCommandBuffer>)buffer;
}
@end
int hfr_mailbox(void){return 1;}
void guest_wait_begin(void){atomic_fetch_add(&waits,1);}
void guest_wait_end(void){atomic_fetch_add(&resumes,1);}
int com_frees(void){return 0;}
int enh_msaa_samples(int *autop){if(autop)*autop=0;return test_samples;}
void texrep_main_frame(id<MTLCommandQueue> q){(void)q;}
int fpscounter_on(void){return 0;}
void fpscounter_note_gpu(double x){(void)x;}
void fpscounter_note_present(void){}
void fpscounter_note_presented(double x){(void)x;}
void hfr_note_present_call(void){}
void hfr_note_presented(double x){(void)x;}
double hfr_present_min_duration(void){return 0;}
static id<MTLTexture> screen;
static id<MTLTexture> texture(unsigned w,unsigned h){
 MTLTextureDescriptor*t=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:w height:h mipmapped:NO];
 t.storageMode=MTLStorageModePrivate;t.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
 return [g_dev newTextureWithDescriptor:t];
}
static void draw(unsigned target,unsigned ps){
 metal_set_render_target(target);g_cur_ps=ps;
 TVert v[3]={0};for(unsigned i=0;i<3;i++){v[i].x=i==1?3:-1;v[i].y=i==2?3:-1;v[i].w=1;}
 metal_draw_tv(v,3,4,0);g_dbuf[g_cur][g_dn[g_cur]-1].vsid=1;
 g_rvn[g_cur]=16;g_kn[g_cur]=16;
}
struct Request{unsigned id,pitch,rows;void*bytes;int result;_Atomic int done;};
static void *read_worker(void*p){struct Request*r=p;@autoreleasepool{r->result=metal_read_texture(r->id,r->bytes,r->pitch,r->rows);}atomic_store(&r->done,1);return NULL;}
static void consume(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);metal_encode_ready(screen,nil,t,t);}
static int read_queued(unsigned texture_id,void*bytes,unsigned pitch,unsigned rows){
 struct Request r={.id=texture_id,.pitch=pitch,.rows=rows,.bytes=bytes};int handled=0;pthread_t worker;assert(!pthread_create(&worker,NULL,read_worker,&r));
 for(unsigned n=0;!atomic_load(&r.done)&&n<5000;n++){
  pthread_mutex_lock(&g_qlock);int ready=g_ready>=0;pthread_mutex_unlock(&g_qlock);
  if(ready&&!handled){
   handled=1;
   if(fail_mode==1)assert(readback_fail_queued());
   else if(fail_mode==2){id<MTLCommandQueue>saved=g_queue;g_queue=(id<MTLCommandQueue>)[RBNullQueue new];consume();g_queue=saved;}
   else if(fail_mode==3){
    id<MTLCommandQueue>saved=g_queue;RBNoRenderQueue*queue=[RBNoRenderQueue new];queue.backing=saved;
    g_queue=(id<MTLCommandQueue>)queue;consume();g_queue=saved;
   }else if(fail_mode==4){
    unsigned count=g_pson;id<MTLRenderPipelineState>saved[MAXPSO]={nil};
    assert(count);for(unsigned i=0;i<count;i++){saved[i]=g_psocache[i].pso;g_psocache[i].pso=nil;}
    consume();assert(g_pson==count);for(unsigned i=0;i<count;i++)g_psocache[i].pso=saved[i];
   }else if(fail_mode==5)metal_request_quit();
   else consume();
  }else usleep(1000);
 }
 assert(atomic_load(&r.done));assert(!pthread_join(worker,NULL));return r.result;
}
static void check(const uint8_t*p,unsigned pitch,unsigned w,unsigned h,uint32_t color){
 for(unsigned y=0;y<h;y++){for(unsigned x=0;x<w;x++)assert(!memcmp(p+y*pitch+x*4,&color,4));for(unsigned x=w*4;x<pitch;x++)assert(p[y*pitch+x]==0xa5);}
}
int main(int argc,char**argv){@autoreleasepool{
 if(argc==2&&!strcmp(argv[1],"msaa"))test_samples=4;
 g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;g_queue=[g_dev newCommandQueue];
 g_layer=[CAMetalLayer layer];g_layer.device=g_dev;g_hd_msn=test_samples;screen=texture(16,16);assert(screen);
 for(unsigned b=0;b<2;b++){g_dbuf[b]=calloc(MAXD,sizeof(MDraw));g_vbuf[b]=calloc(MAXV,sizeof(MVert));g_pscb[b]=calloc(MAXD,sizeof(PSConstants));g_rvbuf[b]=calloc(1,MAXRV);g_kbuf[b]=calloc(1,MAXKB);}
 g_fb_sem=dispatch_semaphore_create(NFB);g_cur_blend=15u<<14;g_cur_cull=1;
 NSError*error=nil;g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:&error];assert(g_lib);
 NSString*source=@"vertex VOut rb_vertex(uint i [[vertex_id]]){VOut o={};float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};o.pos=float4(p[i],.25,1);return o;}fragment float4 ps_1(VOut i [[stage_in]]){return float4(1,0,0,1);}fragment float4 ps_2(VOut i [[stage_in]]){return float4(0,1,0,1);}";
 id<MTLLibrary>lib=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:source] options:nil error:&error];assert(lib);
 g_vsfn[1]=[lib newFunctionWithName:@"rb_vertex"];
 NSString*far_source=[source stringByReplacingOccurrencesOfString:@".25,1" withString:@".75,1"];
 id<MTLLibrary>far_lib=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:far_source] options:nil error:&error];assert(far_lib);
 g_vsfn[2]=[far_lib newFunctionWithName:@"rb_vertex"];g_psfn[1]=[lib newFunctionWithName:@"ps_1"];g_psfn[2]=[lib newFunctionWithName:@"ps_2"];
 MTLPixelFormat formats[4]={MTLPixelFormatBGRA8Unorm,0,0,0};g_pso=pso_for_colors(metal_shader_key(1,1)|(15u<<14),formats);assert(g_pso);
 g_tex[7]=texture(113,64);g_texn=8;g_tex_isrt[7]=1;
 const unsigned pitch=113*4+12,size=pitch*64;uint8_t*allocation=malloc(size+32);memset(allocation,0xa5,size+32);uint8_t*bytes=allocation+16;
 metal_set_render_target(0);metal_clear_target(0xff123456);
 if(test_samples>1){g_cur_depth=(2u<<8)|11u;metal_clear_target_ex(0xff123456,3,1);draw(0,1);g_cur_depth=0;}
 unsigned query=metal_query_create();assert(query&&!metal_query_issue(query,2));
 metal_set_render_target(7);metal_clear_target(0xff654321);draw(7,1);metal_set_render_target(0);
 assert(read_queued(7,bytes,452,64)==1);check(bytes,452,113,64,0xffff0000);
 for(unsigned i=452*64;i<size;i++)assert(bytes[i]==0xa5);
 assert(atomic_load(&g_frames_drawn)==0&&g_gframe==0);uint32_t samples=99;assert(metal_query_get_data(query,0,&samples)==MQ_INVALID&&samples==99);
 draw(7,2);assert(!metal_query_issue(query,1));metal_set_render_target(0);memset(bytes,0xa5,size);
 assert(read_queued(7,bytes,pitch,64)==1);check(bytes,pitch,113,64,0xff00ff00);
 assert(!metal_query_get_data(query,0,&samples)&&samples==2u*113u*64u);metal_query_destroy(query);
 assert(atomic_load(&g_frames_drawn)==0&&g_gframe==0);
 /* The final pass must retain color, and MS depth must reject the farther draw. */
 if(test_samples>1){g_cur_depth=(2u<<8)|9u;draw(0,2);g_dbuf[g_cur][g_dn[g_cur]-1].vsid=2;}
 metal_present();assert(g_ready>=0);consume();id<MTLCommandBuffer>barrier=[g_queue commandBuffer];[barrier commit];[barrier waitUntilCompleted];
 assert(atomic_load(&g_frames_drawn)==1&&g_gframe==1);
 assert(g_logical_frame.draws==(test_samples>1?7u:4u));
 assert(g_logical_frame.verts==(test_samples>1?12u:6u));
 id<MTLBuffer>copy=[g_dev newBufferWithLength:16*16*4 options:MTLResourceStorageModeShared];barrier=[g_queue commandBuffer];id<MTLBlitCommandEncoder>bl=[barrier blitCommandEncoder];
 [bl copyFromTexture:screen sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(16,16,1) toBuffer:copy destinationOffset:0 destinationBytesPerRow:64 destinationBytesPerImage:1024];[bl endEncoding];[barrier commit];[barrier waitUntilCompleted];
 uint32_t*p=copy.contents;for(unsigned i=0;i<256;i++)assert(p[i]==(test_samples>1?0xffff0000u:0xff123456u));
 memset(bytes,0xa5,size);assert(!metal_read_texture(MAXTEX,bytes,pitch,64));assert(!metal_read_texture(7,bytes,1,64));
 assert(!metal_read_texture(7,bytes,pitch,63));assert(!metal_read_texture(7,NULL,pitch,64));
 for(unsigned i=0;i<size+32;i++)assert(allocation[i]==0xa5);
 assert(atomic_load(&waits)>=2&&atomic_load(&waits)==atomic_load(&resumes));
 assert(!atomic_load(&g_frames_dropped)&&!atomic_load(&g_frames_replaced));
 /* Failed production encodes must not expose old pixels even when their
  * readback blit and GPU submission still succeed. */
 for(fail_mode=1;fail_mode<=5;fail_mode++){
  memset(bytes,0xa5,size);g_cur_depth=0;
  unsigned failed_query=metal_query_create();assert(!metal_query_issue(failed_query,2));
  draw(7,1);assert(!metal_query_issue(failed_query,1));
  assert(!read_queued(7,bytes,pitch,64));
  for(unsigned i=0;i<size+32;i++)assert(allocation[i]==0xa5);
  if(fail_mode<5){uint32_t untouched=77;assert(metal_query_get_data(failed_query,0,&untouched)==MQ_LOST&&untouched==77);assert(g_ready==-1&&g_enc_rb==-1);}
  if(fail_mode==3)assert(denied_renders&&forwarded_blits&&forwarded_commits);
  metal_query_destroy(failed_query);
 }
 assert(atomic_load(&waits)==atomic_load(&resumes));
 puts("ordered readback: BGRA/pitch/canaries, repeated draws, spanning query, retained screen and one Present passed");
 free(allocation);
}return 0;}
