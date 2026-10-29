#include "../runtime/metal.m"
#include <assert.h>
#include <unistd.h>
int g_perflog;_Atomic int g_pl_thumb_req;char g_pl_dir[900];_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;__strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX];uint8_t g_texrep_k[TEXREP_MAXTEX];
static void record(float z){TVert v[3]={0};for(int i=0;i<3;i++){v[i].x=i==1?3:-1;v[i].y=i==2?3:-1;v[i].z=z;v[i].w=1;}metal_draw_tv(v,3,4,0);}
static void reset_record(void){assert(!g_mqframe[0].count);g_dn[0]=g_vn[0]=g_pscn[0]=0;}
static id<MTLRenderPipelineState> pipeline;
static id<MTLTexture> color,depth;
static id<MTLDepthStencilState> depth_state;
static id<MTLCommandBuffer> submit(int split){
 MQSubmission *s=mq_capture(0);assert(s);id<MTLBuffer>results=mq_buffer(s);assert(results);
 id<MTLCommandBuffer> cb=[g_queue commandBuffer];id<MTLRenderCommandEncoder> enc=nil;
 for(unsigned i=0;i<s->draws;i++){
  if(!enc || split){if(enc)[enc endEncoding];MTLRenderPassDescriptor*rp=[MTLRenderPassDescriptor new];
   rp.colorAttachments[0].texture=color;rp.colorAttachments[0].loadAction=i?MTLLoadActionLoad:MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
   rp.depthAttachment.texture=depth;rp.depthAttachment.clearDepth=.5;rp.depthAttachment.loadAction=i?MTLLoadActionLoad:MTLLoadActionClear;rp.depthAttachment.storeAction=MTLStoreActionStore;rp.visibilityResultBuffer=results;
   enc=[cb renderCommandEncoderWithDescriptor:rp];[enc setRenderPipelineState:pipeline];[enc setDepthStencilState:depth_state];}
  MDraw*d=&g_dbuf[0][i];float z=g_vbuf[0][d->first].z;[enc setVertexBytes:&z length:4 atIndex:0];mq_encode(enc,results,d,i);
  [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
 }
 if(enc)[enc endEncoding];[cb addCompletedHandler:^(id<MTLCommandBuffer>b){mq_complete(s,results.contents,b.status==MTLCommandBufferStatusCompleted);}];return cb;
}
static void finish(id<MTLCommandBuffer>cb){[cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);}

int hfr_mailbox(void){return 1;}
void guest_wait_begin(void){}
void guest_wait_end(void){}
static void *consume_query_frame(void*unused){
 (void)unused;usleep(90000);
 /* A transient nil drawable consumes the selection signal. The actual
  * retry helper must make the same frame selectable again without losing it. */
 assert(g_ready==0&&atomic_exchange(&g_frame_pending,0));frame_retry_drawable();
 assert(g_ready==0&&atomic_exchange(&g_frame_pending,0));
 MQSubmission*s=mq_capture(0);assert(s);mq_complete(s,NULL,1);
 pthread_mutex_lock(&g_qlock);g_ready=-1;pthread_cond_signal(&g_qcond);pthread_mutex_unlock(&g_qlock);return NULL;
}
static void scheduling(void){
 setenv("PASSMERGE","1",1);setenv("HD_REORDER","1",1);
 unsigned q=metal_query_create();assert(!metal_query_issue(q,2));record(.25);record(.25);record(.25);assert(!metal_query_issue(q,1));
 g_dbuf[0][1].target=42;g_dbuf[0][1].first=1;g_dbuf[0][2].first=2;pass_reorder(0);
 assert(g_dbuf[0][1].first==1&&g_dbuf[0][2].first==2);
 MQSubmission*s=mq_capture(0);mq_complete(s,NULL,0);metal_query_destroy(q);reset_record();
 record(.25);record(.25);record(.25);g_dbuf[0][1].target=42;g_dbuf[0][1].first=1;g_dbuf[0][2].first=2;pass_reorder(0);
 assert(g_dbuf[0][1].first==2&&g_dbuf[0][2].first==1);reset_record();
 q=metal_query_create();assert(!metal_query_issue(q,2));assert(!metal_query_issue(q,1));
 g_ready=0;g_cur=1;atomic_store(&g_frame_pending,1);g_layer=(CAMetalLayer*)[NSObject new];pthread_t worker;assert(!pthread_create(&worker,NULL,consume_query_frame,NULL));
 struct timespec begin,end;clock_gettime(CLOCK_MONOTONIC,&begin);metal_present();clock_gettime(CLOCK_MONOTONIC,&end);pthread_join(worker,NULL);
 double elapsed=end.tv_sec-begin.tv_sec+(end.tv_nsec-begin.tv_nsec)/1e9;
 assert(elapsed>.075&&g_frames_dropped==0&&g_frames_replaced==0&&g_ready==1);
 metal_query_destroy(q);g_ready=-1;g_cur=0;g_layer=nil;reset_record();
}
int main(void){@autoreleasepool{
 g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;g_queue=[g_dev newCommandQueue];
 g_dbuf[0]=calloc(MAXD,sizeof(MDraw));g_vbuf[0]=calloc(MAXV,sizeof(MVert));g_pscb[0]=calloc(MAXD,sizeof(PSConstants));
 NSError*error=nil;NSString*source=@"#include <metal_stdlib>\nusing namespace metal;struct V {float4 pos [[position]];};vertex V vmain(uint id [[vertex_id]],constant float&z [[buffer(0)]]){float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};V o;o.pos=float4(p[id],z,1);return o;}fragment float4 fmain(){return float4(1);}";
 id<MTLLibrary>lib=[g_dev newLibraryWithSource:source options:nil error:&error];assert(lib);
 MTLRenderPipelineDescriptor*pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"vmain"];pd.fragmentFunction=[lib newFunctionWithName:@"fmain"];pd.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;pd.colorAttachments[0].writeMask=MTLColorWriteMaskNone;pd.depthAttachmentPixelFormat=MTLPixelFormatDepth32Float;
 pipeline=[g_dev newRenderPipelineStateWithDescriptor:pd error:&error];assert(pipeline);
 MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:8 height:8 mipmapped:NO];td.usage=MTLTextureUsageRenderTarget;color=[g_dev newTextureWithDescriptor:td];td.pixelFormat=MTLPixelFormatDepth32Float;td.storageMode=MTLStorageModePrivate;depth=[g_dev newTextureWithDescriptor:td];assert(color&&depth);
 MTLDepthStencilDescriptor*dd=[MTLDepthStencilDescriptor new];dd.depthCompareFunction=MTLCompareFunctionLess;dd.depthWriteEnabled=NO;depth_state=[g_dev newDepthStencilStateWithDescriptor:dd];
 uint32_t value=0xabcdef;unsigned q=metal_query_create(),nested=metal_query_create();assert(q&&nested);
 assert(metal_query_issue(q,0)==MQ_INVALID);assert(!metal_query_issue(q,2));assert(metal_query_get_data(q,0,&value)==MQ_INVALID&&value==0xabcdef);
 record(.75);assert(!metal_query_issue(q,1));assert(metal_query_get_data(q,0,&value)==1&&value==0xabcdef);assert(metal_query_get_data(q,1,&value)==MQ_UNAVAILABLE);
 id<MTLCommandBuffer>cb=submit(0);assert(metal_query_get_data(q,1,&value)==1);finish(cb);assert(!metal_query_get_data(q,0,&value)&&value==0);reset_record();
 assert(!metal_query_issue(q,2));record(.25);assert(!metal_query_issue(nested,2));record(.25);assert(!metal_query_issue(q,1));record(.25);assert(!metal_query_issue(nested,1));record(.25);
 cb=submit(0);finish(cb);assert(!metal_query_get_data(q,0,&value)&&value==128);assert(!metal_query_get_data(nested,0,&value)&&value==128);reset_record();
 /* Unique slots survive pass changes. Re-BEGIN before old completion does
  * not expose the old generation, and Release is safe while it is in flight. */
 assert(!metal_query_issue(q,2));record(.25);record(.75);assert(!metal_query_issue(q,1));cb=submit(1);reset_record();
 assert(!metal_query_issue(q,2));record(.75);assert(!metal_query_issue(q,1));id<MTLCommandBuffer>next=submit(0);
 finish(cb);value=99;assert(metal_query_get_data(q,0,&value)==1&&value==99);finish(next);assert(!metal_query_get_data(q,0,&value)&&value==0);reset_record();
 assert(!metal_query_issue(q,2));record(.25);assert(!metal_query_issue(q,1));cb=submit(0);metal_query_destroy(q);finish(cb);assert(metal_query_get_data(q,0,&value)==MQ_INVALID);reset_record();
 assert(!metal_query_issue(nested,2));record(.25);assert(!metal_query_issue(nested,1));cb=submit(0);metal_query_reset();finish(cb);assert(metal_query_get_data(nested,0,&value)==MQ_LOST);metal_query_destroy(nested);reset_record();

 q=metal_query_create();assert(!metal_query_issue(q,2));assert(!metal_query_issue(q,1));cb=submit(0);finish(cb);assert(!metal_query_get_data(q,0,&value)&&value==0);reset_record();
 assert(!metal_query_issue(q,2));record(.25);cb=submit(0);reset_record();record(.25);assert(!metal_query_issue(q,1));next=submit(1);
 finish(cb);assert(metal_query_get_data(q,0,&value)==1);finish(next);assert(!metal_query_get_data(q,0,&value)&&value==128);reset_record();metal_query_destroy(q);
 q=metal_query_create();metal_query_reset();assert(metal_query_issue(q,2)==MQ_LOST);metal_query_destroy(q);
 unsigned handles[MQ_MAX];for(unsigned i=0;i<MQ_MAX;i++){handles[i]=metal_query_create();assert(handles[i]);}assert(!metal_query_create());for(unsigned i=0;i<MQ_MAX;i++)metal_query_destroy(handles[i]);
 scheduling();
 puts("real GPU occlusion: hidden0, visible64/draw, nested128, pass changes, pending, reissue, release and reset passed");
}return 0;}
