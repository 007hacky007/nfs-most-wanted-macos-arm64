/* Vertex format shared by com.c (guest side) and metal.m (draw side).
 * Because the vertex shader runs on the CPU, positions arriving here are
 * in CLIP SPACE; the rasterizer does the perspective divide. */
#ifndef GFX_H
#define GFX_H
#include <stdint.h>
/* Disjoint native pixel shader families; ID zero is fixed function. */
#define METAL_PS_BASE_LIMIT 1024
#define METAL_PS_CUBE_OFFSET 1024
#define METAL_PS_REFLECTION_OFFSET 2048
#define METAL_PS_CAPACITY 2048
#define METAL_PS_ENHANCED_CAPACITY 10240
/* NOTE: texture coordinates carry FOUR components per stage.
 * Previously only .xy was carried, but the game's vertex shaders produce
 * PROJECTED coordinates (measured: oT1.x/y/z = dot(v0, c4..c6),
 * oT1.w = r0.x).  With z/w dropped, the road/car reflections came out
 * streaky and dark. */
typedef struct {
    float x, y, z, w;      /* clip space */
    float r, g, b, a;      /* oD0 - diffuse */
    float r1,g1,b1,a1;     /* oD1 - specular */
    float t[8][4];         /* TEXCOORD0..TEXCOORD7 */
    float col_extra[4][4]; /* SM3 COLOR2..COLOR5 */
} TVert;

unsigned metal_create_texture_volume(unsigned w,unsigned h,unsigned d,unsigned levels,unsigned format);
unsigned metal_create_depth_texture(unsigned w,unsigned h,unsigned zid);
int metal_upload_texture_volume(unsigned id_,unsigned level,const void *data,unsigned pitch,unsigned slice_pitch);
void metal_set_stage_textures(const unsigned textures[16]);
void metal_set_ps_bool(const int booleans[16]);
void metal_set_ps_model(int psid,unsigned version,const int types[16]);
void metal_set_ps_outputs(int psid,unsigned mask);
void metal_set_render_target_at(unsigned slot,unsigned packed_target);
void metal_set_color_write(unsigned slot,unsigned mask);
void metal_set_depth_bias(float constant,float slope);
void metal_set_fixed_function(unsigned mode);

unsigned metal_widescreen_samples(unsigned target);
void metal_widescreen_postfx(unsigned source,unsigned gamma,unsigned border);
void com_widescreen_postfx(unsigned gamma,unsigned border);

unsigned metal_query_create(void);
void metal_query_destroy(unsigned handle);
uint32_t metal_query_issue(unsigned handle,unsigned flags);
uint32_t metal_query_get_data(unsigned handle,unsigned flags,uint32_t *value);
void metal_query_reset(void);

void metal_draw_tv(const TVert *tv, unsigned nverts, unsigned prim, unsigned tex);
#endif
