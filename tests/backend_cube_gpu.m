/* COM-produced target words, actual Metal queue snapshots and cube storage. */
#include "../runtime/metal.m"
#include <assert.h>
int g_perflog;_Atomic int g_pl_thumb_req;char g_pl_dir[900];_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;__strong id<MTLTexture> g_texrep_tex[TEXREP_MAXTEX];uint8_t g_texrep_k[TEXREP_MAXTEX];
int main(int argc,char**argv){@autoreleasepool{
 assert(argc==2);uint32_t targets[12];FILE*f=fopen(argv[1],"rb");assert(f);assert(fread(targets,sizeof targets,1,f)==1);fclose(f);
 g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;g_queue=[g_dev newCommandQueue];
 g_dbuf[0]=calloc(MAXD,sizeof(MDraw));g_vbuf[0]=calloc(MAXV,sizeof(MVert));g_pscb[0]=calloc(MAXD,sizeof(PSConstants));
 unsigned cube=metal_create_texture_cube(16,2,21,1);assert(cube&&g_tex[cube].textureType==MTLTextureTypeCube);
 NSError*error=nil;NSString*src=@"#include <metal_stdlib>\nusing namespace metal;vertex float4 vmain(uint i [[vertex_id]]){float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};return float4(p[i],0,1);}fragment float4 fmain(constant float4 &color [[buffer(0)]]){return color;}";
 id<MTLLibrary>lib=[g_dev newLibraryWithSource:src options:nil error:&error];assert(lib);
 MTLRenderPipelineDescriptor*pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"vmain"];pd.fragmentFunction=[lib newFunctionWithName:@"fmain"];pd.colorAttachments[0].pixelFormat=g_tex[cube].pixelFormat;
 id<MTLRenderPipelineState>pipeline=[g_dev newRenderPipelineStateWithDescriptor:pd error:&error];assert(pipeline);
 TVert vertices[3]={0};for(unsigned i=0;i<3;i++){vertices[i].x=i==1?3:-1;vertices[i].y=i==2?3:-1;vertices[i].w=1;}
 for(unsigned face=0;face<6;face++){
  assert(TGT_ID(targets[face])==7&&TGT_FACE(targets[face])==face+1);
  metal_set_render_target((targets[face]&0xffff0000u)|cube);metal_draw_tv(vertices,3,4,0);
 }
 assert(g_dn[0]==6);metal_set_render_target(0);
 for(unsigned face=0;face<6;face++){
  MDraw*draw=&g_dbuf[0][face];assert(TGT_ID(draw->target)==cube&&TGT_FACE(draw->target)==face+1);
  id<MTLCommandBuffer>cb=[g_queue commandBuffer];MTLRenderPassDescriptor*rp=[MTLRenderPassDescriptor new];
  rp.colorAttachments[0].texture=g_tex[TGT_ID(draw->target)];
  if(TGT_FACE(draw->target))rp.colorAttachments[0].slice=TGT_FACE(draw->target)-1u;
  rp.colorAttachments[0].loadAction=MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
  id<MTLRenderCommandEncoder>enc=[cb renderCommandEncoderWithDescriptor:rp];[enc setRenderPipelineState:pipeline];
  float color[4]={(face+1)/8.f,.25f,.5f,1};[enc setFragmentBytes:color length:sizeof color atIndex:0];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];
  [cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);
  for(unsigned slice=0;slice<6;slice++){
   uint8_t pixels[16*16*4];[g_tex[cube] getBytes:pixels bytesPerRow:64 bytesPerImage:sizeof pixels fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 slice:slice];
   for(unsigned p=0;p<256;p++){
    if(slice<=face){assert(abs((int)pixels[p*4+2]-(int)lroundf((slice+1)*255/8.f))<=1);assert(pixels[p*4]==128&&pixels[p*4+1]==64&&pixels[p*4+3]==255);}
    else for(unsigned c=0;c<4;c++)assert(pixels[p*4+c]==0);
   }
  }
 }
 /* Rendering base faces leaves every higher mip untouched. */
 for(unsigned face=0;face<6;face++){uint8_t pixels[8*8*4];[g_tex[cube] getBytes:pixels bytesPerRow:32 bytesPerImage:sizeof pixels fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:1 slice:face];for(unsigned i=0;i<sizeof pixels;i++)assert(!pixels[i]);}
 puts("six distinct GPU cube faces from actual COM target words; queued faces survive later target changes");
}return 0;}
