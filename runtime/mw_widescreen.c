/*
Native adaptation of NFSMostWanted WidescreenFix projection and movie fitting.
https://github.com/ThirteenAG/WidescreenFixesPack

MIT License

Copyright (c) 2018 ThirteenAG

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
/* Native Most Wanted projection and presentation. */
#include "widescreen.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <strings.h>
#include <time.h>
#include "gamepad.h"
#include "kbd.h"

static float mapping = 1.f;
static float aspect = 4.f / 3.f;
static int have_resolution;
static unsigned device_width, device_height;
static unsigned view;
static unsigned long projections, movies;
static int fix_hud = 1, fix_fov = 1, scaling = 1, movie_mode = 1;
static int auto_fe = 1, auto_movie = 1;
static int force_audio = 1;
static float fe_scale = 1.f, movie_scale = 1.f, rain_scale = .5f;
static int patch_config,patch_invalid,patch_active,old_shadow_config;
static int shadow_res=1024,shadow_auto,shadow_fix=1,shadow_lod,sim_rate=-1,nos_fix=1,nos_position;
static float nos_length=1.f,sim_step,nos_scalar;
static int sim_ready;
static int console_gamma,hide_aa_bug,write_settings;
static int hud_auto,hud_legacy_set,hud_legacy_mode,hud_dirty;
static uint32_t hud_center;
static struct {uint32_t object;float x,y;} hud_original[2];
static struct {uint32_t object;float x,child[5];} minimap_original;
static float left_deadzone=10,right_deadzone=10;
static int right_deadzone_set,camera_enabled,camera_invert,camera_horizontal,improve_pad;
static float camera_timeout=3,camera_return=2,camera_stick_sensitivity=1,camera_mouse_sensitivity=1;
static struct {float yaw,pitch,idle,previous[3],stick_x,stick_y;int previous_valid,mouse_x,mouse_y,last_pad;
               uint32_t mode;int behind;uint64_t activity;} camera;
static uint32_t pad_callback,pad_filename,pad_hashes[14][3];
static int pad_loaded;
static char pad_texture_path[4096];
static int prepare_pad(void);
void dispatch_patch(uint32_t,guest_fn_t);
int metal_display_hz(void);
void com_widescreen_postfx(unsigned gamma,unsigned border);
uint32_t gheap_alloc(int,uint32_t,int);
uint32_t call_guest(CPU *,uint32_t,int,const uint32_t *);
#define HOOK_BRANCH(a,b) a

static int patch_setting(const char *section,const char *key,const char *text){
    int *integer=NULL;float *real=NULL;
    if(!strcmp(section,"MAIN")&&!strcmp(key,"HUDWidescreenMode")){integer=&hud_legacy_mode;hud_legacy_set=1;}
    else if(!strcmp(section,"MISC")||!strcmp(section,"GRAPHICS")){
        if(!strcmp(key,"ShadowsRes")){integer=&shadow_res;if(!strcmp(section,"MISC"))old_shadow_config=1;}
        else if(!strcmp(key,"AutoScaleShadowsRes"))integer=&shadow_auto;
        else if(!strcmp(key,"ShadowsFix"))integer=&shadow_fix;
        else if(!strcmp(key,"ImproveShadowLOD"))integer=&shadow_lod;
        else if(!strcmp(key,"SimRate"))integer=&sim_rate;
        else if(!strcmp(section,"MISC")&&!strcmp(key,"WriteSettingsToFile"))integer=&write_settings;
        else if(!strcmp(key,"ImproveGamepadSupport"))integer=&improve_pad;
        else if(!strcmp(key,"LeftStickDeadzone"))real=&left_deadzone;
        else if(!strcmp(key,"RightStickDeadzone")){real=&right_deadzone;right_deadzone_set=1;}
        else if(!strcmp(section,"GRAPHICS")&&!strcmp(key,"ConsoleGamma"))integer=&console_gamma;
        else if(!strcmp(section,"GRAPHICS")&&!strcmp(key,"HideAABug"))integer=&hide_aa_bug;
    }else if(!strcmp(section,"CAMERA")){
        if(!strcmp(key,"Enable"))integer=&camera_enabled;
        else if(!strcmp(key,"CameraReturnTimeout"))real=&camera_timeout;
        else if(!strcmp(key,"CameraReturnSpeed"))real=&camera_return;
        else if(!strcmp(key,"StickLookSensitivity"))real=&camera_stick_sensitivity;
        else if(!strcmp(key,"MouseLookSensitivity"))real=&camera_mouse_sensitivity;
        else if(!strcmp(key,"InvertLook"))integer=&camera_invert;
        else if(!strcmp(key,"OnlyAllowHorizontalStickMovement"))integer=&camera_horizontal;
    }else if(!strcmp(section,"NOSTrail")){
        if(!strcmp(key,"FixNOSTrailLength"))integer=&nos_fix;
        else if(!strcmp(key,"CustomNOSTrailLength"))real=&nos_length;
        else if(!strcmp(key,"FixNOSTrailPosition"))integer=&nos_position;
    }
    if(!integer&&!real)return 0;
    char *end;float value=strtof(text,&end);
    if(end==text||!isfinite(value)){patch_invalid=1;return 1;}
    while(isspace((unsigned char)*end))end++;
    if(*end|| (integer&&(value<-10000||value>10000||truncf(value)!=value))){patch_invalid=1;return 1;}
    if(integer){
        if(integer==&console_gamma||integer==&hide_aa_bug)value=fmaxf(0,fminf(value,2));
        *integer=(int)value;
    }else *real=value;return 1;
}
static void prepare_sim(void){
    if(sim_ready)return;
    int rate=sim_rate;
    if(rate<0){rate=metal_display_hz();if(rate<=0)rate=60;if(sim_rate==-2)rate*=2;}
    if(!rate)rate=60;
    sim_step=1.f/rate;nos_scalar=((float)rate/60.f)*nos_length;sim_ready=1;
    if(sim_rate)MRF32(0x00903290)=sim_step;
}
static int wide_hud(void){return patch_active&&fix_hud&&(hud_auto||(hud_legacy_set&&hud_legacy_mode));}
int ws_patch_init(void){
    patch_active=0;sim_ready=0;if(!patch_config)return 1;
    if(patch_invalid||shadow_res<0||shadow_res>8192||shadow_auto<0||shadow_auto>1||
       shadow_fix<0||shadow_fix>1||shadow_lod<0||shadow_lod>1||sim_rate<-2||sim_rate>1000||
       nos_fix<0||nos_fix>1||nos_position||nos_length<0||nos_length>16)return 0;
    if(left_deadzone<0||left_deadzone>100||right_deadzone<0||right_deadzone>200||
       write_settings<0||write_settings>1||camera_enabled<0||camera_enabled>1||camera_invert<0||camera_invert>1||camera_horizontal<0||camera_horizontal>1||
       camera_timeout<0||camera_return<0||camera_stick_sensitivity<0||camera_mouse_sensitivity<0||improve_pad<0||improve_pad>2||hud_legacy_mode<0||hud_legacy_mode>1)return 0;
    if(hud_auto&&fix_hud&&!hud_center){hud_center=gheap_alloc(1,8,1);if(!hud_center)return 0;}
    memset(hud_original,0,sizeof hud_original);memset(&minimap_original,0,sizeof minimap_original);
    hud_dirty=1;
    memset(&camera,0,sizeof camera);
    if(improve_pad&&!prepare_pad())return 0;
    /* Raw DirectInput values must reach the guest before its left-store hooks
     * and camera/icon sampling. Historical Full does not own the right stick. */
    gamepad_set_stick_deadzones(0,(right_deadzone_set||camera_enabled||improve_pad)?0:-1.f);
    patch_active=1;
    /* The pinned WS filename occupies the existing 20-byte splash slot. */
    if(wide_hud())memcpy(g_mem+0x008a0114,g_mem+0x0089f828,sizeof "WS_MW_LS_Splash.fng");
    if(shadow_fix)MRF32(0x008a0e50)=60.f;return 1;
}
int ws_registry_default(const char *name,uint32_t *value){
    if(!patch_active||!write_settings||!name||!value)return 0;
    /* Pinned historical WriteSettingsToFile graphics defaults. Stored native
     * preferences take precedence in the registry bridge. */
    static const struct {const char *name;uint32_t value;} defaults[]={
        {"g_CarEnvironmentMapEnable",3},{"g_CarEnvironmentMapUpdateData",1},
        {"g_RoadReflectionEnable",3},{"g_MotionBlurEnable",1},{"g_ParticleSystemEnable",1},
        {"g_WorldLodLevel",3},{"g_CarLodLevel",1},{"g_OverBrightEnable",1},
        {"g_FSAALevel",7},{"g_RainEnable",1},{"g_TextureFiltering",2},
        {"g_RacingResolution",1},{"g_PerformanceLevel",5},{"g_VSyncOn",0},
        {"g_ShadowDetail",2},{"g_VisualTreatment",1}};
    for(unsigned i=0;i<sizeof defaults/sizeof *defaults;i++)if(!strcasecmp(name,defaults[i].name)){
        *value=defaults[i].value;return 1;
    }
    return 0;
}
static float shadow_ratio(void){
    return (have_resolution?(float)device_height/device_width:1.f/aspect)/.85f;
}
static unsigned shadow_width(void){
    float width=(float)shadow_res;
    if(shadow_auto&&fix_fov)width/=shadow_ratio();
    if(width>16384)width=16384;return (unsigned)width;
}

void ws_configure(const char *directory){
    char path[4096], line[512], section[64] = "";
    int n = snprintf(path, sizeof path, "%s/scripts/NFSMostWanted.WidescreenFix.ini", directory);
    if (n < 0 || (size_t)n >= sizeof path) return;
    FILE *f = fopen(path, "r");
    if (!f) return;
    patch_config=1;
    n=snprintf(pad_texture_path,sizeof pad_texture_path,"%s/scripts/NFSMostWanted.WidescreenFix.tpk",directory);
    if(n<0||(size_t)n>=sizeof pad_texture_path)patch_invalid=1;
    while (fgets(line, sizeof line, f)){
        char *comment = strstr(line, "//"); if (comment) *comment = 0;
        char *p = line; while (isspace((unsigned char)*p)) p++;
        if (*p == '['){ sscanf(p, "[%63[^]]]", section); continue; }
        char key[64], text[128]="";
        if (sscanf(p, "%63[^=]=%127[^;\r\n]", key, text) < 1 || !strchr(p,'=')) continue;
        size_t k = strlen(key); while (k && isspace((unsigned char)key[k - 1])) key[--k] = 0;
        if(!strcmp(section,"MAIN")&&!strcmp(key,"HudAspectRatioConstraint")){
            char *end=text+strlen(text);while(end>text&&isspace((unsigned char)end[-1]))*--end=0;
            char *begin=text;while(isspace((unsigned char)*begin))begin++;
            if(!strcasecmp(begin,"Auto")||!*begin)hud_auto=1;else patch_invalid=1;
            continue;
        }
        if(patch_setting(section,key,text))continue;
        char *end; float value = strtof(text, &end);
        if (end == text || !isfinite(value)) continue;
        while (isspace((unsigned char)*end)) end++;
        if (*end) continue;
        if (!strcmp(section, "MAIN")){
            if (!strcmp(key, "FixHUD")) fix_hud = value != 0;
            else if (!strcmp(key, "FixFOV")) fix_fov = value != 0;
            else if (!strcmp(key, "Scaling")) scaling = (int)fmaxf(0, fminf(value, 2));
            else if (!strcmp(key, "FMVWidescreenMode")) movie_mode = (int)fmaxf(0, fminf(value, 2));
            else if (!strcmp(key, "FEScale") && value > 0 && value <= 4) fe_scale = value;
            else if (!strcmp(key, "FMVScale") && value > 0 && value <= 4) movie_scale = value;
            else if (!strcmp(key, "AutoFitFE")) auto_fe = value != 0;
            else if (!strcmp(key, "AutoFitFMV")) auto_movie = value != 0;
        } else if (!strcmp(section, "MISC")){
            if (!strcmp(key, "ForceHighSpecAudio")) force_audio = value != 0;
        } else if (!strcmp(section, "GRAPHICS")){
            if (!strcmp(key, "RainDropletsScale") && value >= 0 && value <= 4) rain_scale = value;
        }
    }
    fclose(f);
    /* SkipIntro stays under the game's control: the native port preserves the movies. */
    fprintf(stderr, "Native widescreen settings: HUD=%d FOV=%d Scaling=%d FMV=%d\n",
            fix_hud, fix_fov, scaling, movie_mode);
}
void ws_set_mapping(float k){ mapping = isfinite(k) && k > 0.f ? k : 1.f; }
void ws_set_resolution(unsigned w, unsigned h){
    if (w && h){if(!have_resolution||device_width!=w||device_height!=h)hud_dirty=1;
        device_width=w; device_height=h; aspect = (float)w / h; have_resolution = 1; }
}
int ws_get_resolution(unsigned *w,unsigned *h){
    if(!have_resolution)return 0;
    if(w)*w=device_width;
    if(h)*h=device_height;
    return 1;
}
float ws_aspect_ratio(void){return aspect;}
int ws_high_spec_audio(void){return force_audio;}
float ws_persp_x(void){ return 1.f; }
float ws_persp_y(void){ return 1.f; }
static float hud_mapping(void){ return have_resolution ? (4.f / 3.f) / aspect : mapping; }
float ws_ui_x(void){ float k = hud_mapping(); return fix_hud ? (auto_fe ? fminf(k, 1.f) : k) * fe_scale : 1.f; }
float ws_ui_y(void){ float k = hud_mapping(); return fix_hud ? (auto_fe ? fminf(1.f / k, 1.f) : 1.f) * fe_scale : 1.f; }
double ws_render_factor(void){ return 1.; }
double ws_max_pixels(void){ return WS_MAX_PIXELS_DEFAULT; }
int ws_fill_target(void){ return 0; }
int ws_take_border_quad(void){ return 0; }
static float world_scale(void){ return (4.f / 3.f) / aspect / (scaling ? 1.047485948f : 1.f); }

/* The stock 2:1, power-of-two movies contain a letterboxed 16:9 image. */
static int power_of_two(unsigned n){ return n && !(n & (n - 1)); }
static void fit_movie(CPU *c){
    uint32_t object = c->ebx, quad = c->esp, texture = MR32(c->esp + 0x48);
    if (!object || !texture) return;
    float ow = fabsf(MRF32(object + 0x30)), oh = fabsf(MRF32(object + 0x44));
    unsigned fw = MR16(texture + 0x44), fh = MR16(texture + 0x46);
    if (!isfinite(ow) || !isfinite(oh) || ow < 1.f || oh < 1.f || !fw || !fh) return;
    int full = ow >= 600.f && oh >= 450.f;
    float content = (float)fw / fh, crop = 0.f;
    if (power_of_two(fw) && power_of_two(fh)){
        content = full ? 4.f / 3.f : ow / oh;
        if (fw == fh * 2){ crop = .125f; content /= .75f; }
    }
    float canvas = fmaxf(480.f * aspect, 640.f);
    float bw = full ? canvas : ow, bh = full ? canvas / aspect : oh;
    float width = bw, height = bw / content, cropx = 0.f, cropy = crop;
    int mode = full ? movie_mode : 0;
    if (auto_movie && aspect < 16.f / 9.f) mode = 0;
    if (mode){
        if (mode == 1){
            if (height > bh) cropy += (1.f - 2.f * crop) * .5f * (1.f - bh / height);
            else cropx = .5f * (1.f - height / bh);
        }
        height = bh;
    } else if (height > bh){ height = bh; width = bh * content; }
    float scale = movie_scale / (fix_hud ? fe_scale : 1.f);
    MRF32(quad) = -.5f * width / ow * scale; MRF32(quad + 4) = -.5f * height / oh * scale;
    MRF32(quad + 8) = -MRF32(quad); MRF32(quad + 12) = -MRF32(quad + 4);
    float u = MRF32(quad + 28) - MRF32(quad + 20);
    float v = MRF32(quad + 32) - MRF32(quad + 24);
    MRF32(quad + 20) += u * cropx; MRF32(quad + 28) -= u * cropx;
    MRF32(quad + 24) += v * cropy; MRF32(quad + 32) -= v * cropy;
    if (full){ void com_clear_movie_borders(void); com_clear_movie_borders(); }
    movies++;
}
static uint32_t pad_hash(const char *text){uint32_t hash=0xffffffffu;while(*text)hash=(unsigned char)*text++ +33u*hash;return hash;}
static int pad_load(CPU *c){
    if(pad_loaded)return 1;
    CPU saved=*c;uint32_t arguments[]={pad_filename,0,0,0,0};
    uint32_t resource=call_guest(c,0x0065fd30,5,arguments);*c=saved;
    if(!resource){fprintf(stderr,"Widescreen controller texture loading failed\n");return 0;}
    c->ecx=resource;c->edx=0;call_guest(c,0x006616f0,2,arguments+1);*c=saved;
    call_guest(c,0x006626b0,0,NULL);*c=saved;pad_loaded=1;return 1;
}
static void pad_visit(CPU *c){
    uint32_t object=MR32(c->esp+4);int success=pad_load(c);
    if(success&&MR32(object+0x18)==1){
        uint32_t handle=MR32(object+0x24);unsigned mode=camera.last_pad?(unsigned)improve_pad:0;
        for(unsigned i=0;i<14;i++)if(handle==pad_hashes[i][0]||handle==pad_hashes[i][1]||handle==pad_hashes[i][2]){
            uint32_t replacement=pad_hashes[i][mode];
            if(handle!=replacement){MR32(object+0x24)=replacement;MR32(object+0x1c)|=0x02400000u;}break;
        }
    }
    c->eax=success;POP32(c->eip);c->esp+=4;
}
static int prepare_pad(void){
    FILE *file=fopen(pad_texture_path,"rb");if(!file)return 0;
    int have_data=fgetc(file)!=EOF;fclose(file);if(!have_data)return 0;
    if(!pad_callback){
        pad_callback=gheap_alloc(1,12,1);pad_filename=gheap_alloc(1,sizeof "scripts\\NFSMostWanted.WidescreenFix.tpk",0);
        if(!pad_callback||!pad_filename)return 0;
        MR32(pad_callback+4)=0xc1000000u;MR32(pad_callback+8)=pad_callback;
        memcpy(g_mem+pad_filename,"scripts\\NFSMostWanted.WidescreenFix.tpk",sizeof "scripts\\NFSMostWanted.WidescreenFix.tpk");
        dispatch_patch(0xc1000000u,pad_visit);
    }
    const char *names[]={"L1","PC_KEY_Q","PC_GREATERTHAN_LESSTHAN","R1","PC_KEY_ENTER","PC_KEY_ESC_FRENCH","PC_KEY_ESC","PC_KEY_1","PC_KEY_2","PC_KEY_3","PC_KEY_4","PC_ARROW_KEYS_UP_DOWN","PC_LOAD","PC_ARROW_KEYS"};
    for(unsigned i=0;i<14;i++){
        pad_hashes[i][0]=pad_hash(names[i]);const char *suffix=!strncmp(names[i],"PC_",3)?names[i]+3:names[i];char text[64];
        snprintf(text,sizeof text,"XBOX_%s",suffix);pad_hashes[i][1]=pad_hash(text);
        snprintf(text,sizeof text,"PS_%s",suffix);pad_hashes[i][2]=pad_hash(text);
    }
    pad_loaded=0;return 1;
}
static void service_pad(CPU *c){
    CPU saved=*c;uint32_t package=MR32(c->ecx+0xe0),argument=pad_callback+8;
    while(package){
        c->ecx=package;c->edx=0;call_guest(c,0x005b1560,1,&argument);*c=saved;
        uint32_t next=MR32(package+4);if(next==package)break;package=next;
    }
}
enum { WS_KEY_SOURCE=3 };
static void pad_buttons(CPU *c){
    uint32_t state=c->esi+0x234;
    MR32(0x008f3514)=MR32(state+36)!=0;
    MR32(0x008f3584)=MR32(state+20)!=0;
    MR32(0x008f34f8)=MR32(state+40)!=0;
    if(MR32(state+44)&&MR32(state+48)&&MR32(0x00925e90)==3){
        kbd_set_key(WS_KEY_SOURCE,0x10,1);kbd_post(0x100,0x51,0x00100001);kbd_post(0x102,'q',0x00100001);
        kbd_set_key(WS_KEY_SOURCE,0x10,0);kbd_post(0x101,0x51,0xc0100001u);
    }
}
static void pad_label(CPU *c){
    static const char *original[]={" 2"," 3"," 4"," 5"," 6"," 7"," 8"," 9"," 10"," 1"," Up"," Down"," Left"," Right","X Rotation","Y Rotation","X Axis","Y Axis","Z Axis","Hat Switch"};
    static const char *xbox[]={"B","X","Y","LB","RB","View (Select)","Menu (Start)","Left stick","Right stick","A","D-pad Up","D-pad Down","D-pad Left","D-pad Right","Right stick Left/Right","Right stick Up/Down","Left stick Left/Right","Left stick Up/Down","LT / RT","D-pad"};
    static const char *playstation[]={"Circle","Square","Triangle","L1","R1","Select","Start","L3","R3","Cross","D-pad Up","D-pad Down","D-pad Left","D-pad Right","Right stick Left/Right","Right stick Up/Down","Left stick Left/Right","Left stick Up/Down","L2 / R2","D-pad"};
    char *text=(char*)g_mem+MR32(c->esp+4);
    for(unsigned i=0;i<20;i++)if(strstr(text,original[i])){strcpy(text,improve_pad==2?playstation[i]:xbox[i]);break;}
}
static float hud_offset(void){volatile float scaled=aspect*240.f;return scaled-320.f;}
static void position_hud(CPU *c){
    CPU saved=*c;uint32_t package=MR32(c->esi+0x24);
    const uint32_t hashes[]={0x1603009eu,0x5d0101f1u};
    for(unsigned side=0;side<2;side++){
        uint32_t find[]={package,hashes[side]};uint32_t object=call_guest(c,0x00524850,2,find);*c=saved;
        if(!object)continue;
        if(hud_original[side].object!=object){
            uint32_t get[]={object,hud_center,hud_center+4};call_guest(c,0x00524ee0,3,get);*c=saved;
            hud_original[side].object=object;hud_original[side].x=MRF32(hud_center);hud_original[side].y=MRF32(hud_center+4);
        }
        float x=hud_original[side].x+(side?hud_offset():-hud_offset());uint32_t bits;memcpy(&bits,&x,4);
        uint32_t y;memcpy(&y,&hud_original[side].y,4);uint32_t set[]={object,bits,y};
        call_guest(c,0x00525050,3,set);*c=saved;
    }
    hud_dirty=0;
}
static void position_minimap(uint32_t object,int wide){
    const unsigned fields[]={60,64,68,72,144};
    if(minimap_original.object!=object){
        minimap_original.object=object;minimap_original.x=MRF32(object+184);
        for(unsigned i=0;i<5;i++)minimap_original.child[i]=MRF32(MR32(MR32(object+fields[i])+44)+28);
    }
    float offset=wide?-hud_offset():hud_offset();
    MRF32(0x0091cf04)=wide?offset:0;MRF32(0x0091cf0c)=wide?-.9375f:.9375f;
    MRF32(object+184)=minimap_original.x+offset;
    for(unsigned i=0;i<5;i++)MRF32(MR32(MR32(object+fields[i])+44)+28)=minimap_original.child[i]+offset;
    MR32(MR32(MR32(object+144)+44)+32)=MR32(object+188);
}
static void refresh_hud(CPU *c){
    CPU saved=*c;uint32_t object=c->esi;int wide=MR8(object+816)!=0;
    uint32_t arguments[]={wide?0x62ed04ecu:0x53ec068cu,MR32(object+0x24),0};
    c->ecx=MR32(0x0091cadc);call_guest(c,0x00516c90,3,arguments);*c=saved;
    position_hud(c);uint32_t minimap=MR32(object+800);if(minimap)position_minimap(minimap,wide);
    hud_dirty=0;
}
static int hud_layout(void){return patch_active&&fix_hud&&(hud_auto||hud_legacy_set);}
static uint64_t camera_clock(void){struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);return (uint64_t)ts.tv_sec*1000000000u+ts.tv_nsec;}
static int stick_assigned(void){
    for(unsigned action=0;action<=18;action++)for(unsigned slot=0;slot<4;slot++)
        if(MR32(0x0091f41c+action*52+slot*12)==6)return 1;
    return 0;
}
static void camera_look(CPU *c){
    camera.activity=camera_clock();
    if(camera.behind||(camera.mode!=2&&camera.mode!=3)){
        camera.yaw=camera.pitch=camera.idle=0;camera.previous_valid=0;return;
    }
    uint32_t from=MR32(c->esp+4),to=MR32(c->esp+8);float dt=MRF32(0x00988dec),speed=0;
    if(camera.previous_valid&&dt>0){float dx=MRF32(to)-camera.previous[0],dy=MRF32(to+4)-camera.previous[1];speed=sqrtf(dx*dx+dy*dy)/dt;}
    for(unsigned i=0;i<3;i++)camera.previous[i]=MRF32(to+4*i);camera.previous_valid=1;
    float sx=-camera.stick_x,sy=camera_horizontal?0:camera.stick_y;
    if(!camera_horizontal&&stick_assigned())sx=sy=0;
    float dx=sx-camera.mouse_x*(camera_mouse_sensitivity*.15f),dy=sy+camera.mouse_y*(camera_mouse_sensitivity*.15f);
    camera.mouse_x=camera.mouse_y=0;
    if(fabsf(dx)>.01f||fabsf(dy)>.01f){camera.yaw+=dx*camera_stick_sensitivity;camera.pitch+=dy*camera_stick_sensitivity*(camera_invert?-1.f:1.f);camera.idle=0;}
    else{
        camera.idle+=dt;
        if(camera.idle>=camera_timeout&&speed>.5f){
            float blend=1.f-expf(-camera_return*dt),difference=-camera.yaw;
            while(difference>180)difference-=360;while(difference<-180)difference+=360;
            camera.yaw+=difference*blend;camera.pitch+=(0-camera.pitch)*blend;
            if(fabsf(camera.yaw)<.3f&&fabsf(camera.pitch)<.3f)camera.yaw=camera.pitch=0;
        }
    }
    if(camera.yaw==0&&camera.pitch==0)return;
    camera.pitch=fmaxf(-30,fminf(camera.pitch,60));
    float vx=MRF32(from)-MRF32(to),vy=MRF32(from+4)-MRF32(to+4),vz=MRF32(from+8)-MRF32(to+8);
    float distance=sqrtf(vx*vx+vy*vy+vz*vz),planar=sqrtf(vx*vx+vy*vy);
    float yaw=atan2f(vy,vx)+camera.yaw*.0174533f,pitch=atan2f(vz,planar)+camera.pitch*.0174533f;
    pitch=fmaxf(-1.39626f,fminf(pitch,1.39626f));
    MRF32(from)=MRF32(to)+distance*cosf(pitch)*cosf(yaw);
    MRF32(from+4)=MRF32(to+4)+distance*cosf(pitch)*sinf(yaw);
    MRF32(from+8)=MRF32(to+8)+distance*sinf(pitch);
}
static uint32_t left_stick_value(uint32_t raw){
    double value=(double)raw/65535.0-.5;
    if(fabs(value)<=left_deadzone/200.f)value=0;
    return (uint32_t)((value+.5)*65535.0);
}
static void capture_stick(CPU *c){
    uint32_t state=c->ebp-0x13c;double x=((int32_t)MR32(state+12)-32767.5)/32767.5,y=((int32_t)MR32(state+16)-32767.5)/32767.5;
    float deadzone=right_deadzone>0?right_deadzone/200.f:0;
    if(fabs(x)<=deadzone)x=0;if(fabs(y)<=deadzone)y=0;camera.stick_x=(float)x;camera.stick_y=(float)y;
    int input=0;for(unsigned i=0;i<32;i++)if(MR8(state+48+i)&0x80)input=1;
    if(fabs(x)>.01||fabs(y)>.01||fabs(((int32_t)MR32(state)-32767.5)/32767.5)>.01||
       fabs(((int32_t)MR32(state+4)-32767.5)/32767.5)>.01)input=1;
    if(input)camera.last_pad=1;
}

int ws_hook(CPU *c, uint32_t ip){
    double *st = &c->st[c->top & 7];
    switch (ip){
    case HOOK_SITE(0x007f2ae9):if(patch_active&&improve_pad)pad_buttons(c);return 1;
    case HOOK_SITE(0x006282d3):if(patch_active&&improve_pad)pad_label(c);return 1;
    case HOOK_SITE(0x005a3146):if(wide_hud())MR32(c->esp)=0xc4df3ff2u;return 1;
    case HOOK_SITE(0x005a3141):if(patch_active&&improve_pad)MR32(c->esp)=improve_pad==2?0xdc64c04cu:0xd18d4c4cu;return 1;
    case HOOK_SITE(0x005c53c0):if(patch_active&&improve_pad)service_pad(c);return 1;
    case HOOK_SITE(0x005696ce):
        if(hud_layout()){c->eax=(c->eax&~255u)|(unsigned)(hud_auto?1:hud_legacy_mode);
            if(hud_auto&&hud_dirty)refresh_hud(c);}return 1;
    case HOOK_SITE(0x0058d886):
        if(hud_layout())c->eax=(c->eax&~255u)|(unsigned)(hud_auto?1:hud_legacy_mode);return 1;
    case HOOK_SITE(0x0057cb85):case HOOK_SITE(0x0056885d):
        if(hud_layout()){uint32_t a=(ip==0x0057cb85?c->edx:c->ecx)&255u,b=(unsigned)(hud_auto?1:hud_legacy_mode),result=a-b;FLAGS_SUB(a,b,result,8);}return 1;
    case HOOK_SITE(0x0047d416):
        if(patch_active&&camera_enabled){camera.behind=MR8(c->esi+0xa1);camera.mode=MR32(c->esi+0x9c);}return 1;
    case HOOK_SITE(0x0047dcbc):if(patch_active&&camera_enabled)camera_look(c);return 1;
    case HOOK_SITE(0x007f29b8):if(patch_active&&left_deadzone)MR32(c->esi+0x234)=left_stick_value(c->eax);return 1;
    case HOOK_SITE(0x007f29ca):if(patch_active&&left_deadzone)MR32(c->esi+0x238)=left_stick_value(c->edx);return 1;
    case HOOK_SITE(0x007f2981):if(patch_active&&(camera_enabled||improve_pad))capture_stick(c);return 1;
    case HOOK_SITE(0x007f201d):
        if(patch_active&&(camera_enabled||improve_pad)){
            camera.mouse_x=(int32_t)MR32(c->ebp-0x14);camera.mouse_y=(int32_t)MR32(c->ebp-0x10);
            if(camera.mouse_x||camera.mouse_y||MR32(c->ebp-0xc))camera.last_pad=0;
        }return 1;
    case HOOK_SITE(0x007f21cf):
        if(patch_active&&(camera_enabled||improve_pad))for(unsigned i=0;i<256;i++)if(MR8(c->ebp-0x130+i)&0x80){camera.last_pad=0;break;}
        return 1;
    case HOOK_SITE(0x005696f6):case HOOK_SITE(0x00569717):
        if(patch_active&&hud_auto&&fix_hud)position_hud(c);return 1;
    case HOOK_SITE(0x006e75ac):
        if(patch_active&&(console_gamma||hide_aa_bug))com_widescreen_postfx((unsigned)console_gamma,(unsigned)hide_aa_bug);
        return 1;
    case HOOK_SITE(0x006c149f):
        if(patch_active&&old_shadow_config&&shadow_res)c->ecx=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c14e1):
        if(patch_active&&old_shadow_config&&shadow_res)c->ecx=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c15db):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c165b):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c16db):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c16fd):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c1a97):
        if(patch_active&&old_shadow_config&&shadow_res)c->ecx=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c1b6f):
        if(patch_active&&old_shadow_config&&shadow_res){uint32_t a=MR32(0x008f23f0),b=0x1002,result=a-b;FLAGS_SUB(a,b,result,32);}return 1;
    case HOOK_SITE(0x006c509a):
        if(patch_active&&old_shadow_config&&shadow_res){uint32_t a=MR32(0x008f23f0),b=0x10de,result=a-b;FLAGS_SUB(a,b,result,32);}return 1;
    case HOOK_SITE(0x006c50ea):
        if(patch_active&&old_shadow_config&&shadow_res){uint32_t a=MR32(0x008f23f0),b=0x8086,result=a-b;FLAGS_SUB(a,b,result,32);}return 1;
    case HOOK_SITE(0x006c5f08):
        if(patch_active&&old_shadow_config&&shadow_res)c->ebp=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c5f52):
        if(patch_active&&old_shadow_config&&shadow_res)c->ebp=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006cfdb5):
        if(patch_active&&old_shadow_config&&shadow_res)c->edx=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006cfdfa):
        if(patch_active&&old_shadow_config&&shadow_res)c->edx=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006d2105):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006d5c39):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006d5de1):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006df920):
        if(patch_active&&old_shadow_config&&shadow_res)c->eax=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006df9a3):
        if(patch_active&&old_shadow_config&&shadow_res){uint32_t a=MR32(0x008f23f0),b=0x1002,result=a-b;FLAGS_SUB(a,b,result,32);}return 1;
    case HOOK_SITE(0x006e6b6f):
        if(patch_active&&old_shadow_config&&shadow_res)c->ecx=MR32(0x008f23f0);return 1;
    case HOOK_SITE(0x006c86b5):
        /* The original scans again after each write. A 1024-wide first
         * replacement retains its signature and is selected twice. */
        if(patch_active&&shadow_res){unsigned width=shadow_width();c->eax=old_shadow_config&&width==1024?(unsigned)shadow_res:width;}return 1;
    case HOOK_SITE(0x006c86c5):
        if(patch_active&&shadow_res)c->eax=old_shadow_config&&shadow_width()==1024?1024:(unsigned)shadow_res;return 1;
    case HOOK_SITE(0x006c8790):case HOOK_SITE(0x006c87c2):
        if(patch_active&&shadow_res){MR32(c->esp)=shadow_width();MR32(c->esp+4)=(unsigned)shadow_res;}return 1;
    case HOOK_SITE(0x006e550d):
        if(patch_active&&shadow_res&&shadow_width()>2048){float bias=(shadow_width()/2048.f)*4.f;memcpy(&c->edx,&bias,4);}return 1;
    case HOOK_SITE(0x006e5178):if(patch_active&&shadow_lod)MR32(c->esp)=0;return 1;
    case HOOK_SITE(0x006bffa6):if(patch_active&&shadow_lod)MR32(c->esp)=0x6102;return 1;
    case HOOK_SITE(0x006de383):if(patch_active&&shadow_fix)MR32(0x00982ba8)=0;return 1;
    case HOOK_SITE(0x006e4668):case HOOK_SITE(0x006e46ac):case HOOK_SITE(0x006e47e4):case HOOK_SITE(0x006e482c):
        if(patch_active&&fix_fov){int32_t width=(int32_t)((float)(int32_t)MR32(c->ebx+0xc4)/shadow_ratio());
            if(ip==0x006e4668)c->eax=(uint32_t)width;else if(ip==0x006e482c)c->edx=(uint32_t)width;else c->ecx=(uint32_t)width;}
        return 1;
    case HOOK_SITE(0x00666104):if(patch_active&&sim_rate){prepare_sim();MRF32(c->esp)=sim_step;}return 1;
    case HOOK_SITE(0x0075aad8):if(patch_active&&(sim_rate||nos_fix))prepare_sim();return 1;
    case HOOK_SITE(0x004c41f9):
        /* Equivalent to the supplied fix's fallback immediate replacement.
         * Preserve X360's 48 kHz path and the later explicit game override. */
        if(force_audio&&MR32(0x008ee650)==22050u)MR32(0x008ee650)=44100u;
        return 1;
    case HOOK_SITE(0x006cf4f6):
        view = c->ecx;
        if (fix_fov) *st = view == 3 ? .4 : 1.;
        projections++; return 1;
    case HOOK_SITE(0x006cf56c):
        if (fix_fov && (view == 1 || view == 4)) *st *= world_scale();
        return 1;
    case HOOK_SITE(0x006cf57e):
        if (fix_fov && (view == 1 || view == 4)) *st *= .43434 / .5;
        return 1;
    case HOOK_SITE(0x006cf5e2):
        if (fix_fov && (view == 1 || view == 4)) *st *= scaling == 2 ? 1.27 : scaling ? 1.21 : 1.215;
        return 1;
    case HOOK_SITE(0x006e466c):
    case HOOK_SITE(0x006e47f0):
        if (fix_fov) *st = 1.;
        return 1;
    case HOOK_SITE(0x006e46b6):
    case HOOK_SITE(0x006e4836):
        if (fix_fov) *st *= world_scale();
        return 1;
    case HOOK_SITE(0x006d4811): *st *= rain_scale / aspect; return 1;
    case HOOK_SITE(0x006d482f): *st *= rain_scale; return 1;
    case HOOK_SITE(0x006c9659):
        if (fix_fov){
            /* The pinned X360 patch already uses its own 10x operand. */
            double factor=(double)1.1f;
            if(MR32(0x006c9655)==0x0102f0d0u){float value=MRF32(0x0102f0d0);if(isfinite(value)&&value>0)factor=value;}
            *st *= 10. / factor;
        }
        return 1;
    case HOOK_SITE(0x006c9c4b): *st *= aspect * .75f; return 1;
    case HOOK_SITE(0x006d4c21): *st *= (4.f / 3.f) / aspect; return 1;
    case HOOK_SITE(0x0059a03f): fit_movie(c); return 1;
    case HOOK_SITE(0x00591460):
        /* The pinned X360 movie wrapper reset these UVs after fit_movie.
         * For PC letterboxed movies, retain that caller's single crop. */
        if(MR32(c->esp)==0x0100992cu&&MR32(c->ebp+4)==0x0059a044u&&!MR8(0x0102b560))
            for(unsigned i=0;i<4;i++)MR32(c->esp+0x18+4*i)=MR32(c->ebp+0x1c+4*i);
        return 1;
    default: return 0;
    }
}
int ws_branch(CPU *c,uint32_t ip){
    switch(ip){
    case HOOK_BRANCH(0x005a3080,0x005a3082):return wide_hud();
    case HOOK_BRANCH(0x005a30b1,0x005a30b6):
        if(!wide_hud())return 0;
        /* One object argument; the caller retains all three live slots. */
        {CPU saved=*c;uint32_t object=MR32(c->esp);call_guest(c,0x00514cc0,1,&object);*c=saved;}return 1;
    case HOOK_BRANCH(0x00628a52,0x00628a58):
        if(!patch_active||!improve_pad)return 0;
        c->st[c->top]*=.0078125f;MR32(0x0091fabc)=0;MR32(0x0091faf0)=1;MR32(0x0091fc90)=3;return 1;
    case HOOK_BRANCH(0x0056fdb0,0x00570561):
        return patch_active&&camera_enabled&&camera.activity&&camera_clock()-camera.activity<100000000u;
    case HOOK_BRANCH(0x005678a0,0x00567945):
        if(!patch_active||!hud_auto||!fix_hud)return 0;position_minimap(c->ecx,MR8(c->esp+4)!=0);return 1;
    case HOOK_BRANCH(0x006de377,0x006de379):return patch_active&&shadow_fix;
    case HOOK_BRANCH(0x006612ea,0x006612f0):
        if(!patch_active||!sim_rate)return 0;prepare_sim();ST(0)*=(double)sim_step;return 1;
    case HOOK_BRANCH(0x0065c78d,0x0065c793):case HOOK_BRANCH(0x0065c7d7,0x0065c7dd):
        if(!patch_active||!sim_rate)return 0;prepare_sim();FPUSH((double)sim_step);return 1;
    case HOOK_BRANCH(0x00745038,0x00745040):
        if(!patch_active||!nos_fix)return 0;prepare_sim();
        {uint32_t first=c->edx,second=c->esi,dest=c->esp+0x30;
         for(unsigned i=0;i<3;i++){float delta=MRF32(first+4*i)-MRF32(second+4*i);float result=delta*nos_scalar;
             MRF32(dest+4*i)=result;memset(&c->xmm[0],0,sizeof c->xmm[0]);c->xmm[0].f[0]=result;}
         c->ecx=second;c->edx=dest;c->eax=0;FLAGS_LOG(0,32);}
        return 1;
    default:return -1;
    }
}
void ws_report(void){
    fprintf(stderr, "Native widescreen: aspect %.4f, mapping %.4f, %lu projections, %lu movie quads\n",
            aspect, mapping, projections, movies);
}
