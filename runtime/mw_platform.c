/* Optional NFSU2 integrations are absent until verified for this game. */
#include "cpu.h"
#include <stdio.h>
#include <stdint.h>

int g_dx_in_pass, g_fxtr, g_efx_stat, g_prof_on;
uint32_t g_last_fn;
void guest_hook(CPU *c,uint32_t ip){ (void)c; fprintf(stderr,"Unregistered guest hook %08x\n",ip); __builtin_trap(); }
void autotest_note_trap(uint32_t a,const char *n){ (void)a;(void)n; }
void autotest_note_unimpl(const char *d,const char *n,uint32_t a){ (void)d;(void)n;(void)a; }
void overrides_report(void){}
void d3dx_hle_report(void){}
void headlights_report(void){}
int fxtr_now(void){ return 0; }
void cov_reset(void){}
void cov_report(const char *s){ (void)s; }
void genexec_report(void){}
void ws_set_mapping(float k){ (void)k; }
float ws_persp_x(void){ return 1.f; }
float ws_persp_y(void){ return 1.f; }
float ws_ui_x(void){ return 1.f; }
float ws_ui_y(void){ return 1.f; }
double ws_render_factor(void){ return 1.; }
double ws_max_pixels(void){ return 9e6; }
int ws_fill_target(void){ return 0; }
int ws_take_border_quad(void){ return 0; }
void ws_report(void){}
int hfr_mailbox(void){ return 0; }
int hfr_uncapped(void){ return 0; }
void hfr_note_vsync(double a,double b){ (void)a;(void)b; }
double hfr_present_min_duration(void){ return 0.; }
void hfr_note_presented(double a){ (void)a; }
void hfr_note_present_call(void){}
uint64_t hfr_vclock_floor_us(void){ return 4000; }
void discord_lifecycle_changed(void){}
void roam_game_parked(int a){ (void)a; }
void app_local_network_notice(void){}
long autotest_frame(void){ extern uint64_t g_mw_frame;return (long)g_mw_frame; }
const char *autotest_screen(void){ return "unknown"; }
void discord_shutdown(void){}
void garage_profile_deleted(const char *s){ (void)s; }
void garage_profile_written(const char *s){ (void)s; }
const char *hfr_mode_label(void){ return "game"; }
int hfr_mode_off(void){ return 1; }
int hfr_mode_rate(void){ return 60; }
int hfr_rate_now(void){ return 60; }
double hfr_sim_ms(void){ return 0.; }
uint64_t hfr_paced_sleep_us(void){ return 0; }
void watch_arm(uint32_t a){ g_watch_addr=a; g_watch_val=a?MR32(a):0; }
void watch_dump(const char *s,int n){ (void)n; fprintf(stderr,"%s: watch %08x\n",s,g_watch_addr); }
const char *language_registry(void){ return "English"; }
void carsfx_mix(float *a,unsigned n,unsigned r){ (void)a;(void)n;(void)r; }
void horn_mix(float *a,unsigned n,unsigned r){ (void)a;(void)n;(void)r; }
void olfilter_lobby_mark(uint32_t l,uint8_t *p,int n){ (void)l;(void)p;(void)n; }
void olfilter_lobby_sent(uint32_t l,uint8_t *p,int n){ (void)l;(void)p;(void)n; }
