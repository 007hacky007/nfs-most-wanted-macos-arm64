/* Native Most Wanted projection, aspect-correct HUD and movie framing. */
#ifndef WIDESCREEN_H
#define WIDESCREEN_H
#include <stdint.h>
#include "cpu.h"

/* Mark a guest instruction where ws_hook gets control first.  gen.sh greps
 * the runtime sources for HOOK_SITE(0x00xxxxxx) and passes the list to the lifter
 * (HOOKS=), which emits guest_hook(c, va) before that instruction. */
#define HOOK_SITE(va) (va##u)

/* Game aspect / device aspect (com.c res_pick).  1 = the device has the
 * game's own aspect; < 1 = wider screen (Hor+), > 1 = narrower (Vert+). */
void  ws_set_mapping(float k);
void  ws_set_resolution(unsigned width, unsigned height);
/* Actual device pixels, distinct from the game's logical HUD/cursor canvas.
 * Returns 0 without writing outputs until the first device size is selected. */
int   ws_get_resolution(unsigned *width, unsigned *height);
float ws_aspect_ratio(void);
int   ws_high_spec_audio(void);
void  ws_configure(const char *game_directory);
/* Apply selected INI patches after guest memory is mapped. Missing INI is
 * legacy mode; invalid or unsupported patch options return 0. */
int   ws_patch_init(void);
/* Missing graphics values only; persisted registry values must take precedence. */
int   ws_registry_default(const char *name, uint32_t *value);
/* Native replacement edge: 1 takes the edge, 0 runs the original, -1 unknown. */
int   ws_branch(CPU *c, uint32_t ip);
/* Projection hooks correct each game view; the renderer fits the 4:3 HUD. */
float ws_persp_x(void);
float ws_persp_y(void);
float ws_ui_x(void);
float ws_ui_y(void);
/* Render size relative to the window's backing pixels (1 = 1:1). */
double ws_render_factor(void);
/* Shared upper bound for native display rows and initial window sizing. */
#define WS_MAX_PIXELS_DEFAULT 9.0e6
double ws_max_pixels(void);
/* Optional draw exceptions used by the shared renderer. */
int   ws_fill_target(void);
int   ws_take_border_quad(void);
/* 1 if the hook at ip was a widescreen site (guest_hook returns then). */
int   ws_hook(CPU *c, uint32_t ip);
void  ws_report(void);

#endif
