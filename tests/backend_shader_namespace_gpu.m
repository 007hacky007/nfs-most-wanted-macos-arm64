/* Synthetic shader identities, queued selection and production PSO keys. */
#include "../runtime/metal.m"
#include <assert.h>
int g_perflog;_Atomic int g_pl_thumb_req;char g_pl_dir[900];_Atomic long g_mw_dump_frame;
int g_texrep_frame_on;__strong id<MTLTexture>g_texrep_tex[TEXREP_MAXTEX];uint8_t g_texrep_k[TEXREP_MAXTEX];
int com_frees(void){return 0;}
static void register_color(unsigned shader,unsigned r,unsigned g,unsigned b,char source[256]){
 snprintf(source,256,"fragment float4 ps_%u(VOut i [[stage_in]]) { return float4(%u,%u,%u,1); }",shader,r,g,b);
 metal_register_ps(shader,source);assert(g_psfn[shader]);
}
static void pixel(unsigned shader,unsigned vertex,uint32_t expected){
 MTLPixelFormat formats[4]={MTLPixelFormatBGRA8Unorm,0,0,0};
 uint64_t key=metal_shader_key(shader,vertex)|(15u<<14);
 assert(((key>>20)&0x3fffu)==shader&&((key>>34)&0x3ffu)==vertex);
 id<MTLRenderPipelineState>pipeline=pso_for_colors(key,formats);assert(pipeline);
 MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:formats[0] width:4 height:4 mipmapped:NO];
 td.usage=MTLTextureUsageRenderTarget;td.storageMode=MTLStorageModeShared;
 id<MTLTexture>color=[g_dev newTextureWithDescriptor:td];td.pixelFormat=MTLPixelFormatDepth32Float;td.storageMode=MTLStorageModePrivate;
 id<MTLTexture>depth=[g_dev newTextureWithDescriptor:td];assert(color&&depth);
 MTLRenderPassDescriptor*pass=[MTLRenderPassDescriptor new];pass.colorAttachments[0].texture=color;
 pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
 pass.depthAttachment.texture=depth;pass.depthAttachment.loadAction=MTLLoadActionClear;pass.depthAttachment.storeAction=MTLStoreActionDontCare;
 id<MTLCommandBuffer>cb=[g_queue commandBuffer];id<MTLRenderCommandEncoder>enc=[cb renderCommandEncoderWithDescriptor:pass];assert(enc);
 [enc setRenderPipelineState:pipeline];[enc setCullMode:MTLCullModeNone];[enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];
 [cb commit];[cb waitUntilCompleted];assert(cb.status==MTLCommandBufferStatusCompleted);
 uint32_t pixels[16];[color getBytes:pixels bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,4,4) mipmapLevel:0];
 for(unsigned i=0;i<16;i++)assert(pixels[i]==expected);
}
static void queued(unsigned ps,unsigned model,unsigned expected){
 int types[16]={0};types[0]=3;metal_set_ps_model(ps,model,types);metal_set_ps(ps,NULL);
 TVert v[3]={0};for(unsigned i=0;i<3;i++)v[i].w=1;
 unsigned before=g_dn[0];metal_draw_tv(v,3,4,7);assert(g_dn[0]==before+1&&g_dbuf[0][before].ps==(int)expected);
 float raw[12]={0},constant[4]={0};before=g_dn[0];assert(metal_draw_raw(raw,3,16,4,7,1,constant,1));
 assert(g_dn[0]==before+1&&g_dbuf[0][before].ps==(int)expected);
}
int main(void){@autoreleasepool{
 setenv("HD_SSR","0",1);g_dev=MTLCreateSystemDefaultDevice();if(!g_dev)return 77;g_queue=[g_dev newCommandQueue];
 NSError*error=nil;g_lib=[g_dev newLibraryWithSource:kShaderSrc options:nil error:&error];assert(g_lib);
 NSString*vertex=@"vertex VOut namespace_vertex(uint i [[vertex_id]]) { VOut o={};float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};o.pos=float4(p[i],.25,1);return o;}";
 id<MTLLibrary>library=[g_dev newLibraryWithSource:[kPrelude stringByAppendingString:vertex] options:nil error:&error];assert(library);
 g_vsfn[1]=[library newFunctionWithName:@"namespace_vertex"];g_vsfn[511]=g_vsfn[1];
 unsigned cube=2+PSCUBE;char base2[256],cube2[256],water[256],last[256];
 register_color(2,0,0,1,base2);register_color(cube,0,1,0,cube2);register_color(258,1,0,0,water);
 assert(!strcmp(g_ps_source[258].UTF8String,water));assert(!strcmp(g_ps_source[cube].UTF8String,cube2));
 assert(g_psfn[cube]!=g_psfn[258]&&cube!=258);
 assert(PSCUBE==METAL_PS_CUBE_OFFSET&&PSREFL==METAL_PS_REFLECTION_OFFSET);
 assert(MAXPS==(NFS_ENHANCED?METAL_PS_ENHANCED_CAPACITY:METAL_PS_CAPACITY));
 g_dbuf[0]=calloc(MAXD,sizeof(MDraw));g_vbuf[0]=calloc(MAXV,sizeof(MVert));g_pscb[0]=calloc(MAXD,sizeof(PSConstants));g_rvbuf[0]=calloc(1,MAXRV);g_kbuf[0]=calloc(1,MAXKB);g_tex_cube[7]=1;
 queued(2,0x0200,cube);queued(258,0x0300,258);queued(2,0x0300,2);
 pixel(g_dbuf[0][0].ps,1,0xff00ff00);pixel(g_dbuf[0][2].ps,1,0xffff0000);pixel(g_dbuf[0][4].ps,1,0xff0000ff);
 /* Highest normal cube ID and highest supported VS must remain independent. */
 unsigned top=METAL_PS_CAPACITY-1;register_color(top,1,0,1,last);pixel(top,511,0xffff00ff);
 uint64_t all=metal_shader_key(0x3fff,0x3ff);
 assert(all==(((1ull<<24)-1)<<20));assert(!(all&color_write_key(0xfff)));
 assert(metal_shader_key(top,511)!=metal_shader_key(top,255));
#if NFS_ENHANCED
 unsigned stage3=(METAL_PS_BASE_LIMIT-1)+METAL_PS_CUBE_OFFSET+4*METAL_PS_REFLECTION_OFFSET;
 assert(stage3==10239&&stage3==MAXPS-1);register_color(stage3,1,1,0,last);pixel(stage3,511,0xffffff00);
 assert(metal_shader_key(stage3,511)!=metal_shader_key(stage3&0xfff,511));
#endif
 puts("shader namespace: cube2/base258 colors, queued SM2/SM3, high PS/VS keys passed");
}return 0;}
