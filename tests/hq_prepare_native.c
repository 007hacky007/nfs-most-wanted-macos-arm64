/* Handwritten guest-interface model, not generated game or mod code. */
#include "../runtime/hq_prepare.c"
#include <assert.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
static guest_fn_t sim_handler;
static unsigned mode,calls,captures,after_boundary,tuple_mask,heat,light=1,freeze;
static uint32_t heap_next=0x2000000;
static const char *asset_fixture;
int win_keyboard_call(CPU*,const char*,uint32_t*);
uint32_t host_ms(void){return 1;}
void win32_post_message(uint32_t m,uint32_t w,uint32_t l){(void)m;(void)w;(void)l;}
int win32_msg_room(void){return 1;}
void mem_commit(uint32_t p,uint32_t n){assert((uint64_t)p+n<=0x3000000);for(uint32_t i=p>>14;i<=((p+n-1)>>14);i++)g_cbits[i>>3]|=1u<<(i&7);}
uint32_t gheap_alloc(int h,uint32_t n,int z){(void)h;uint32_t p=heap_next;heap_next+=(n+15)&~15u;mem_commit(p,n);if(z)memset(g_mem+p,0,n);return p;}
void gheap_free(int h,uint32_t p){(void)h;(void)p;}
int hq_plugin_enabled(void){return 1;}
int fileio_resolve_game(const char*n,char*p,size_t z){assert(!strcmp(n,"GLOBAL/GlobalB.lzc"));if(!asset_fixture)return 0;return snprintf(p,z,"%s",asset_fixture)>0;}
void dispatch_patch(uint32_t p,guest_fn_t f){if(p==0xc1001000)sim_handler=f;else {assert(p>=DISPATCH_TEXT_BASE&&p-DISPATCH_TEXT_BASE<DISPATCH_TEXT_SIZE);g_dtab[p-DISPATCH_TEXT_BASE]=f;}}
void hq_capture(CPU*c,const char*r,uint32_t a){(void)c;(void)a;assert(!strcmp(r,"boot")||!strcmp(r,"xenoninit")||!strcmp(r,"cartypes")||!strcmp(r,"eohotkeys"));captures++;}
static unsigned async_key(CPU*c,unsigned key){uint32_t saved=c->esp,result;c->esp=0x180000;MR32(c->esp)=key;MR32(c->esp+4)=0;assert(win_keyboard_call(c,"GetAsyncKeyState",&result));c->esp=saved;return result;}
static void interface_call(CPU*c,uint32_t p,uint32_t ecx,uint32_t arg,unsigned clean){uint32_t saved=c->esp;c->esp=0x181000;c->ecx=ecx;MR32(c->esp)=0x1234;MR32(c->esp+4)=arg;guest_fn_t f=p==0xc1001000?sim_handler:dispatch_fast(p);assert(f);f(c);assert(c->eip==0x1234&&c->esp==0x181004+clean);c->esp=saved;}
uint32_t call_guest(CPU*c,uint32_t fn,int argc,const uint32_t*args){
 calls++;MR32(c->fs_base)=0xbad; c->eax=0x123;c->cf^=1;
 if(fn==MW_ENTRY){
  /* The observer runs before Win32 pops the return address. */
  c->eip=0x777777;MR32(c->esp)=mode==1?0x01007add:0x01007ade;MR32(c->esp+12)=mode==2?0x01007b11:0x01007b10;
  if(mode==4)return 0;
  hq_prepare_import(c,mode==3?"CreateWindowExA":mode==5?"CreateThreadpoolWork":"CreateThread");after_boundary++;return 0;
 }
 if(fn==0x02404940){assert(argc==2&&args[0]==0x8a9160&&args[1]==1);c->fs_base=0x1a0000;return 1;}
 if(fn==0x0180ad50){assert(c->esi==0x200100);hq_prepare_checkpoint(c,mode==6?3:1);after_boundary++;return 0;}
 assert(fn==0x01c04a50&&argc==0);
 unsigned f=async_key(c,0x73),h=async_key(c,'H'),k=async_key(c,0x76);
 assert(!(async_key(c,0x73)&1)&&!(async_key(c,'H')&1)&&!(async_key(c,0x76)&1));
 if(f&1)freeze^=1;if(k&1)heat^=1;
 if(h&1){interface_call(c,0x6881c0,eo.vehicle,7,4);light=!c->eax;interface_call(c,light?0x669360:0x669380,eo.vehicle,7,4);}
 interface_call(c,0xc1001000,eo.player,0,0);assert(c->eax==eo.sim);
 uint32_t text=0x190000;MR8(text)='X';interface_call(c,0x5983c0,0,text,0);
 tuple_mask|=1u<<(heat*4+light*2+freeze);
 hq_prepare_checkpoint(c,mode==7?2:3);after_boundary++;return 0;
}
static void old_handler(CPU*c){(void)c;assert(0);}
int main(int argc,char **argv){
 g_mem=calloc(1,0x3000000);assert(g_mem);mem_commit(0,0x3000000);
 if(argc==3){asset_fixture=argv[1];uint32_t chunk=load_car_types();assert(!!chunk==!!atoi(argv[2]));if(chunk){assert(MR32(chunk)==0x34600&&MR32(chunk+4)==8+97*208&&MR8(chunk+16)==0xa5);}free(g_mem);puts("HQ_PREPARE_ASSET_OK");return 0;}
 CPU c;memset(&c,0xa5,sizeof c);c.esp=0x100000;c.fs_base=0x1b0000;CPU before=c;MR32(c.fs_base)=0xabcde;
 hq_prepare_import(&c,"CreateThread");hq_prepare_checkpoint(&c,1);assert(!memcmp(&c,&before,sizeof c)&&MR32(c.fs_base)==0xabcde);
 for(mode=0;mode<6;mode++){
  captures=after_boundary=0;assert(prepare_call(&c,PREP_BOOT,MW_ENTRY,0,NULL,0)==(mode==0));
  assert(captures==(mode==0)&&!memcmp(&c,&before,sizeof c)&&MR32(c.fs_base)==0xabcde);
  assert(after_boundary==(mode==5));
 }
 mode=0;uint32_t a[]={0x8a9160,1};assert(prepare_call(&c,PREP_XENON,0x02404940,2,a,0));assert(!memcmp(&c,&before,sizeof c)&&MR32(c.fs_base)==0xabcde);
 for(mode=0;mode<=6;mode+=6){assert(prepare_call(&c,PREP_CARS,0x0180ad50,0,NULL,0x200100)==(mode==0));assert(!memcmp(&c,&before,sizeof c)&&MR32(c.fs_base)==0xabcde);}
 for(unsigned i=0;i<4;i++)g_dtab[eo_targets[i]-DISPATCH_TEXT_BASE]=old_handler;
 uint8_t saved_globals[sizeof eo_globals/sizeof *eo_globals][4];
 for(unsigned i=0;i<sizeof eo_globals/sizeof *eo_globals;i++){memset(g_mem+eo_globals[i].address,0x5a,eo_globals[i].size);memcpy(saved_globals[i],g_mem+eo_globals[i].address,eo_globals[i].size);}
 mode=0;assert(prepare_eo(&c));assert(tuple_mask==255&&light==1&&heat==1&&freeze==0&&!sim_handler);
 for(unsigned i=0;i<4;i++)assert(dispatch_fast(eo_targets[i])==old_handler);
 for(unsigned i=0;i<sizeof eo_globals/sizeof *eo_globals;i++)assert(!memcmp(saved_globals[i],g_mem+eo_globals[i].address,eo_globals[i].size));
 assert(!memcmp(&c,&before,sizeof c)&&MR32(c.fs_base)==0xabcde&&!kbd_key_down(0x3e)&&!kbd_key_down(0x41)&&!kbd_key_down(0x23));
 mode=7;assert(!prepare_eo(&c));assert(!sim_handler&&!memcmp(&c,&before,sizeof c)&&MR32(c.fs_base)==0xabcde);
 for(unsigned i=0;i<4;i++)assert(dispatch_fast(eo_targets[i])==old_handler);
 for(unsigned i=0;i<sizeof eo_globals/sizeof *eo_globals;i++)assert(!memcmp(saved_globals[i],g_mem+eo_globals[i].address,eo_globals[i].size));
 assert(!kbd_key_down(0x3e)&&!kbd_key_down(0x41)&&!kbd_key_down(0x23));
 unsigned oldcalls=calls;assert(!hq_prepare_run(&c)&&calls==oldcalls);assert(!memcmp(&c,&before,sizeof c));
 g_cbits[c.fs_base>>17]=0;assert(!prepare_call(&c,PREP_BOOT,MW_ENTRY,0,NULL,0)&&calls==oldcalls);
 free(g_mem);puts("HQ_PREPARE_BOUNDARIES_OK");return 0;
}
