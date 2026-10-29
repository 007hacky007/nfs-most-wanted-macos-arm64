from pathlib import Path
import hashlib,re,subprocess,tempfile,unittest
MODULE=Path('runtime/mw_hdreflections.c')
HEADER=r'''
#include "cpu.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t *g_mem;guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
static const char *configuration;static unsigned width=1920,height=1080,allocations;static int resolution_ready=1;
int fileio_resolve_game(const char*name,char*out,size_t capacity){assert(!strcmp(name,"scripts/NFSMWHDReflections.ini"));return snprintf(out,capacity,"%s",configuration)<(int)capacity;}
void metal_game_size(unsigned*w,unsigned*h){*w=640;*h=480;}
int ws_get_resolution(unsigned*w,unsigned*h){if(!resolution_ready)return 0;if(w)*w=width;if(h)*h=height;return 1;}
uint32_t gheap_alloc(int heap,uint32_t size,int zero){assert(heap==1&&size==200&&zero);allocations++;memset(g_mem+0x20000,0,size);return 0x20000;}
int mw_hdreflections_init(int);
int mw_hdreflections_hook(CPU*,uint32_t),mw_hdreflections_branch(CPU*,uint32_t);
void guest_hook(CPU*c,uint32_t ip){assert(mw_hdreflections_hook(c,ip));}
int guest_branch(CPU*c,uint32_t ip){int r=mw_hdreflections_branch(c,ip);assert(r>=0);return r;}
static uint32_t calls[40],call_ecx[40],call_sp[40],call_args[40][2],call_third[40];static unsigned call_count;
void dispatch_indirect(CPU*c,uint32_t fn){
 unsigned n=call_count++;assert(n<40);calls[n]=fn;call_ecx[n]=c->ecx;call_sp[n]=c->esp;
 call_args[n][0]=MR32(c->esp+4);call_args[n][1]=MR32(c->esp+8);
 call_third[n]=MR32(c->esp+12);
 if(fn==0x6c00d0){for(unsigned i=0;i<4;i++)MR32(c->ecx+0x24+4*i)=0x5000+16*i;}
 if(fn==0x507770){
  c->esp-=8;PUSH32(c->ebp);PUSH32(c->edi);c->edi=MR32(c->esp+0x14);c->ecx=MR32(c->edi+4);c->eax=1;
  assert(mw_hdreflections_hook(c,0x507781));assert(c->eax==2);POP32(c->edi);POP32(c->ebp);c->esp+=8;
 }
 POP32(c->eip);
 if(fn==0x723fa0)c->esp+=8;
 if(fn==0x6d04e0||fn==0xfe000002)c->esp+=4;
 if(fn==0xfe000003)c->esp+=12;
}
'''
class HDReflectionsTests(unittest.TestCase):
    def run_native(self,body,fragments='',configuration=None):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);ini=directory/'mod.ini';ini.write_text(configuration if configuration is not None else Path('out/installed/.nfsmw/full/scripts/NFSMWHDReflections.ini').read_text())
            path=directory/'test.c';path.write_text(HEADER+fragments+'\nint main(int argc,char**argv){assert(argc==2);configuration=argv[1];g_mem=calloc(1,0x02000000);CPU cpu={0},*c=&cpu;c->esp=0x8000;c->fcw=0x027f;'+body+'\nfree(g_mem);}')
            result=subprocess.run(['clang','-O1','-fno-strict-aliasing','-Iruntime',str(path),str(MODULE),'-lm','-o',str(directory/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(directory/'test'),str(ini)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
    def test_installed_preset_resolutions_and_memory_sizes(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));assert(allocations==1);
assert(MR32(0x8f9008)==960&&MR32(0x8f900c)==180);
assert(MR32(0x8f5790)==0xbe6e0&&MR32(0x8f7ef0)==0x1cc00);
c->edi=240;c->esi=320;MR32(c->esp)=320;MR32(c->esp+4)=240;
assert(mw_hdreflections_hook(c,0x6bcdfa));assert(MR32(c->esp)==1920&&MR32(c->esp+4)==1080&&c->edi==240&&c->esi==320);
assert(mw_hdreflections_hook(c,0x6bce34));assert(MR32(c->esp)==1920&&MR32(c->esp+4)==1080);
assert(mw_hdreflections_hook(c,0x6bd547));assert(MR32(c->esp)==1080);
assert(mw_hdreflections_hook(c,0x6bd591));assert(MR32(c->esp)==1080&&MR32(c->esp+4)==1080);
assert(mw_hdreflections_hook(c,0x6bd34a));assert(c->edx==1080);
assert(mw_hdreflections_hook(c,0x6bd502));assert(c->ecx==256);
c->ecx=0x30000;assert(mw_hdreflections_hook(c,0x6cfc31));assert(MR32(c->ecx+0x14)==1920&&MR32(c->ecx+0x18)==1080);
unsigned large[]={0x5f7399,0x5f73b5};for(unsigned i=0;i<2;i++){mw_hdreflections_hook(c,large[i]);assert(MR32(c->esp)==0x2c8000);}
mw_hdreflections_hook(c,0x665fdf);assert(MR32(c->esp)==0x8000);
mw_hdreflections_hook(c,0x5009d6);assert(MR32(c->esp)==2048000);
mw_hdreflections_hook(c,0x5009e0);assert(MR32(c->esp)==2048000);
c->eax=0x31000;assert(mw_hdreflections_branch(c,0x500a00)==1);assert(c->eax==0x31000+2048000);
mw_hdreflections_hook(c,0x500a16);assert(MR32(0x915f7c)==2048000);
''')
    def test_autores_waits_for_physical_device_and_tracks_resize(self):
        self.run_native(r'''
resolution_ready=0;MR32(0x8f9008)=123;MR32(0x8f900c)=456;
assert(mw_hdreflections_init(1));assert(MR32(0x8f9008)==123&&MR32(0x8f900c)==456);
MR32(c->esp)=320;MR32(c->esp+4)=240;mw_hdreflections_hook(c,0x6bcdfa);
assert(MR32(c->esp)==320&&MR32(c->esp+4)==240);
resolution_ready=1;mw_hdreflections_hook(c,0x6bcfb7);
assert(MR32(0x8f9008)==960&&MR32(0x8f900c)==180);
mw_hdreflections_hook(c,0x6bcdfa);assert(MR32(c->esp)==1920&&MR32(c->esp+4)==1080);
width=2560;height=1440;mw_hdreflections_hook(c,0x6bd547);assert(MR32(c->esp)==1440);
assert(MR32(0x8f9008)==1280&&MR32(0x8f900c)==240);
''')
    def test_disabled_mode_does_not_allocate_read_config_or_mutate_cpu(self):
        hooks=','.join(re.findall(r'HOOK_SITE\((0x[0-9a-f]+)\)',MODULE.read_text()))
        branches=','.join(re.findall(r'HOOK_BRANCH\((0x[0-9a-f]+)',MODULE.read_text()))
        self.run_native(r'''
configuration="unavailable";assert(mw_hdreflections_init(0));CPU saved=*c;MR32(0x8f9008)=123;
unsigned hooks[]={'''+hooks+r'''};
for(unsigned i=0;i<sizeof hooks/sizeof *hooks;i++){assert(mw_hdreflections_hook(c,hooks[i]));assert(!memcmp(c,&saved,sizeof *c));}
unsigned branches[]={'''+branches+r'''};
for(unsigned i=0;i<sizeof branches/sizeof *branches;i++){assert(!mw_hdreflections_branch(c,branches[i]));assert(!memcmp(c,&saved,sizeof *c));}
assert(!mw_hdreflections_branch(c,0x500a00));assert(!allocations&&MR32(0x8f9008)==123);
assert(!mw_hdreflections_hook(c,1)&&mw_hdreflections_branch(c,1)==-1);
''')

    def test_custom_resolution_scaling_and_unsupported_config(self):
        preset=Path('out/installed/.nfsmw/full/scripts/NFSMWHDReflections.ini').read_text()
        config=preset.replace('AutoRes = 1','AutoRes = 0').replace('CubemapScale = 1.0','CubemapScale = 1.5').replace('MirrorScale = 1.0','MirrorScale = 0.5').replace('RoadScale = 1.0','RoadScale = 2.0').replace('OldGPUCompatibility = 0','OldGPUCompatibility = 1')
        self.run_native(r'''
resolution_ready=0;assert(mw_hdreflections_init(1));assert(MR32(0x8f9008)==128&&MR32(0x8f900c)==128);
mw_hdreflections_hook(c,0x6bd547);assert(MR32(c->esp)==256);
mw_hdreflections_hook(c,0x6bcdfa);assert(MR32(c->esp)==640&&MR32(c->esp+4)==480);
''',configuration=config)
        for option in ('RestoreDetails = 2','RestoreCars = 1','VehicleReflectionBrightness = 2.0','RestoreDetails = 1junk','RestoreDetails =','AutoRes = -1','CubemapScale = nan','CubemapScale = 1e300'):
            section='RESOLUTION' if option.startswith(('AutoRes','CubemapScale')) else 'GENERAL'
            self.run_native('assert(!mw_hdreflections_init(1));assert(!allocations);',configuration=preset+'\n['+section+']\n'+option+'\n')
    def test_lod_flags_match_actual_binary_immediate_load(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));c->esi=0x6000;c->ecx=123;c->ebx=3;MR32(0x982af4)=0;
assert(mw_hdreflections_branch(c,0x6bfe3d)==1);assert(c->ecx==0x982af4&&!c->zf);
c->esi=0x919730;c->ecx=456;assert(mw_hdreflections_branch(c,0x6bfe3d)==1);assert(c->ecx==456&&c->zf);
MR32(c->esp)=0x1000;mw_hdreflections_hook(c,0x6bfe5c);assert(MR32(c->esp)==0x6002);
MR32(c->esp)=0x1100;mw_hdreflections_hook(c,0x6bfec1);assert(MR32(c->esp)==0x1100);
MR32(c->esp)=0x1000;mw_hdreflections_hook(c,0x6bfec1);assert(MR32(c->esp)==0x6002);
mw_hdreflections_hook(c,0x6bff24);assert(MR32(c->esp)==0x600);
c->eax=0x200;assert(mw_hdreflections_branch(c,0x7293d9)==1);assert(!c->zf);
''')
    def test_details_call_order_and_original_stack_cleanup(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));c->ebx=0x5eed;
assert(mw_hdreflections_branch(c,0x6de96d)==1);
uint32_t expected[]={0x723fa0,0x6e2f50,0x7538d0,0x750b10,0x6e2f50,0x6d04e0};
assert(call_count==6&&!memcmp(calls,expected,sizeof expected));
assert(call_ecx[0]==0x80e0&&call_args[0][0]==0x919730&&call_args[0][1]==1);
assert(call_args[2][0]==0x919730&&call_args[2][1]==0);
assert(call_args[3][0]==0x919730&&call_args[3][1]==0x5eed);
assert(call_ecx[5]==0x20000&&call_args[5][0]==0x919730);
assert(c->esp==0x7ff8&&MR32(c->esp)==0x919730&&MR32(c->esp+4)==0x5eed);
''')
    def test_traffic_mask_override_is_limited_to_its_nested_call(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));MR32(0x919734)=3;MR32(c->esp)=0x919730;MR32(c->esp+4)=0;
c->eax=19;assert(mw_hdreflections_hook(c,0x507781));assert(c->eax==19);
assert(mw_hdreflections_branch(c,0x6de9f0)==1);assert(call_count==2&&calls[0]==0x507770&&calls[1]==0x505e80);
assert(call_args[1][0]==0x919730&&call_args[1][1]==0x919730&&c->esp==0x8008);
c->eax=37;assert(mw_hdreflections_hook(c,0x507781));assert(c->eax==37);
''')
    def test_extra_sunflare_constructor_and_failed_query_cleanup(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));assert(mw_hdreflections_hook(c,0x6db265));
assert(call_count==1&&calls[0]==0x6c00d0&&call_ecx[0]==0x20000&&c->esp==0x8000);
for(unsigned i=0;i<4;i++)MR32(0x5000+16*i)=0x6000;
MR32(0x6008)=0xfe000002;MR32(0x2002c)=0;call_count=0;
assert(mw_hdreflections_hook(c,0x6db0fe));assert(call_count==3&&c->esp==0x8000&&c->edi==0x93e04c);
for(unsigned i=0;i<4;i++)assert(MR32(0x20024+4*i)==0);
assert(mw_hdreflections_hook(c,0x6e6db2));assert(call_count==4&&calls[3]==0x6c00d0);
''')
    def test_actual_supplied_caves_match_native_registers_flags_and_calls(self):
        from tools.lift import Lifter
        import pefile
        image=Path('out/installed/.nfsmw/full/scripts/NFSMWHDReflections.asi')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                         'bf545db63d6ea04e4f9dcfa90291224285ee39ab64034b4345c708e6c8b4ba46')
        lifter=Lifter(str(image));pe=pefile.PE(str(image));fragments=''
        for start in (0x10002f30,0x10002f90,0x10003020,0x10003060,0x10003130):
            code,_=lifter.lift(start)
            # Stop at the real cave exit rather than dispatching a whole game.
            code=re.sub(r'DISPATCH_TAIL\(c, (MR32\([^;]+)\);[^\n]*',r'c->eip=\1;return;',code)
            fragments+=code+'\n'
        setup='free(g_mem);g_mem=calloc(1,0x11000000);assert(g_mem);\n'
        for address in (0x1003db00,0x1003db14,0x1003db20,0x1003db58,0x1003db60,
                        0x1003db70,0x1003db88,0x1003db90,0x1003dbb0,0x1003daf8,0x1003dbc0,
                        0x1003db8c,0x1003dae4):
            value=int.from_bytes(pe.get_data(address-0x10000000,4),'little')
            setup+=f'MR32(0x{address:x})=0x{value:x};\n'
        self.run_native(setup+r'''
assert(mw_hdreflections_init(1));MR8(0x1003ef67)=1;MRF32(0x1003dbc4)=.5f;
CPU initial=*c,reference,native;unsigned views[]={1,3,18,20,0xffffffff};
for(unsigned i=0;i<5;i++){
 *c=initial;c->esi=0x6000;c->edi=0x7000;c->ebx=77;MR32(0x6004)=views[i];
 sub_10003020(c);if(c->eip==0x6e73a6)PUSH32(0x466a6000);reference=*c;
 *c=initial;c->esi=0x6000;c->edi=0x7000;c->ebx=77;PUSH32(c->ebx);PUSH32(0);c->ecx=c->edi;PUSH32(0x466a6000);
 mw_hdreflections_hook(c,0x6e73ab);native=*c;reference.eip=native.eip;
 assert(!memcmp(&reference,&native,sizeof native));
 *c=initial;MR32(0x982a20)=0x6000;MR32(0x6004)=2;MR32(0x9195e4+2*0x70)=views[i];MRF32(0x8f935c)=2;
 sub_10003060(c);reference=*c;
 *c=initial;FPUSH(2);mw_hdreflections_hook(c,0x6db5c4);native=*c;reference.eip=native.eip;
 assert(!memcmp(&reference,&native,sizeof native));
}
for(unsigned i=0;i<2;i++){
 *c=initial;c->esi=i?0x919730:0x6000;c->ecx=123;
 sub_10003130(c);reference=*c;assert(c->eip==0x6bfe57);
 *c=initial;c->esi=i?0x919730:0x6000;c->ecx=123;
 assert(mw_hdreflections_branch(c,0x6bfe3d));native=*c;reference.eip=native.eip;
 assert(!memcmp(&reference,&native,sizeof native));
}
for(unsigned i=0;i<5;i++){
 *c=initial;c->edi=0x6000;MR32(0x6004)=views[i];sub_10002f90(c);reference=*c;
 *c=initial;c->edi=0x6000;int take=mw_hdreflections_branch(c,0x74e816);native=*c;
 assert(reference.eip==(take?0x74e818:0x74e843));reference.eip=native.eip;
 assert(!memcmp(&reference,&native,sizeof native));
}
*c=initial;c->ebx=0x5eed;call_count=0;sub_10002f30(c);reference=*c;
uint32_t reference_calls[6],reference_ecx[6],reference_args[6][2];
assert(call_count==6);memcpy(reference_calls,calls,sizeof reference_calls);
memcpy(reference_ecx,call_ecx,sizeof reference_ecx);memcpy(reference_args,call_args,sizeof reference_args);
*c=initial;c->ebx=0x5eed;call_count=0;assert(mw_hdreflections_branch(c,0x6de96d));native=*c;
assert(call_count==6&&!memcmp(reference_calls,calls,sizeof reference_calls)&&!memcmp(reference_args,call_args,sizeof reference_args));
reference_ecx[5]=0x20000;assert(!memcmp(reference_ecx,call_ecx,sizeof reference_ecx));
reference.ecx=native.ecx;reference.eip=native.eip;assert(!memcmp(&reference,&native,sizeof native));
FILE *settings=fopen(configuration,"a");assert(settings);fputs("\n[GENERAL]\nImproveReflectionLOD=0\n",settings);fclose(settings);
assert(mw_hdreflections_init(1));MR8(0x1003ef67)=0;
*c=initial;c->ebx=0x5eed;call_count=0;sub_10002f30(c);reference=*c;assert(call_count==5);
*c=initial;c->ebx=0x5eed;call_count=0;assert(mw_hdreflections_branch(c,0x6de96d));native=*c;assert(call_count==5);
reference.ecx=native.ecx;reference.eip=native.eip;assert(!memcmp(&reference,&native,sizeof native));
''',fragments)

    def test_enabled_water_lastgen_and_flare_edges_preserve_arguments(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));c->eax=0x1234;c->ebx=0x5678;c->zf=1;
MR32(c->esp)=123;MR32(c->esp+4)=456;CPU before=*c;
unsigned branches[]={0x6bfef7,0x6de508,0x504c56,0x738207,0x729479,0x6db5ab,0x4fae9a,0x4faeb0};
for(unsigned i=0;i<sizeof branches/sizeof *branches;i++){
 assert(mw_hdreflections_branch(c,branches[i]));assert(!memcmp(c,&before,sizeof *c));
 assert(MR32(c->esp)==123&&MR32(c->esp+4)==456);
}
mw_hdreflections_hook(c,0x6de81e);assert(MR32(c->esp)==0&&!memcmp(c,&before,sizeof *c));
''')

    def test_canonical_resource_and_pool_instructions_keep_original_layout(self):
        from tools.lift import Lifter
        image=Path('game/speed.exe')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),
                         '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        hooks={int(value,16) for value in re.findall(r'HOOK_SITE\((0x[0-9a-f]+)\)',MODULE.read_text())}
        lifter=Lifter(str(image));lifter.fafter={};fragments=''
        # The shipped patch writes byte 0x06 at 0x6bff21, changing PUSH
        # 0x00000800 into PUSH 0x00000600 before the hook at 0x6bff24.
        instruction=next(lifter.md.disasm(lifter.TDATA[0x6bff1f-lifter.TVA:0x6bff24-lifter.TVA],0x6bff1f))
        self.assertEqual((instruction.mnemonic,instruction.op_str,instruction.size),('push','0x800',5))
        ranges=((0x6bcdee,0x6bcdfa),(0x6bce32,0x6bce38),(0x6bd542,0x6bd547),
                (0x6bd58f,0x6bd591),(0x6bd344,0x6bd34d),(0x6bd4fc,0x6bd507),
                (0x6cfc23,0x6cfc34),(0x5f7394,0x5f739b),(0x500a0c,0x500a1b),
                (0x6bff1f,0x6bff25))
        for start,stop in ranges:
            lifter.entry=start;fragments+=f'void fragment_{start:x}(CPU*c){{\n'
            instructions=list(lifter.md.disasm(lifter.TDATA[start-lifter.TVA:stop-lifter.TVA],start))
            self.assertEqual(instructions[-1].address+instructions[-1].size,stop)
            for instruction in instructions:
                if instruction.address in hooks:fragments+=f'guest_hook(c,0x{instruction.address:x});\n'
                fragments+='\n'.join(lifter.insn(instruction,set()))+'\n'
            if stop in hooks:fragments+=f'guest_hook(c,0x{stop:x});\n'
            fragments+='}\n'
        self.run_native(r'''
assert(mw_hdreflections_init(1));c->eax=0x1234;fragment_6bcdee(c);
assert(c->edi==240&&c->esi==320&&c->esp==0x7ff8&&MR32(c->esp)==1920&&MR32(c->esp+4)==1080);
c->esp=0x8000;c->ecx=0x6000;MR32(0x6074)=0xfe000003;fragment_6bce32(c);
assert(call_count==1&&call_args[0][0]==0x1234&&call_args[0][1]==1920&&call_third[0]==1080&&c->esp==0x8000);
c->edi=128;fragment_6bd542(c);assert(MR32(c->esp)==1080&&MR32(c->esp+4)==1&&MR32(c->esp+8)==1);
c->esp=0x8000;fragment_6bd58f(c);assert(MR32(c->esp)==1080&&MR32(c->esp+4)==1080);
c->esp=0x8000;c->esi=0x7000;c->eax=0x8888;MR32(0x8f8ff4)=128;fragment_6bd344(c);
assert(c->edx==1080&&MR32(0x7018)==0x8888);fragment_6bd4fc(c);assert(c->ecx==256&&c->edi==16);
c->ecx=0x7100;c->ebx=0x2222;fragment_6cfc23(c);assert(MR32(0x7114)==1920&&MR32(0x7118)==1080&&MR32(0x7110)==0x2222);
c->ecx=77;fragment_5f7394(c);assert(MR32(c->esp)==0x2c8000&&c->esi==77);
c->eax=0x99;fragment_500a0c(c);assert(MR32(0x915f7c)==2048000&&MR32(0x915f88)==0x99);
fragment_6bff1f(c);assert(MR32(c->esp)==0x99&&MR32(c->esp+4)==0x600);
''',fragments)

    def test_render_distance_and_frontend_culling_match_view_types(self):
        self.run_native(r'''
assert(mw_hdreflections_init(1));c->esi=0x6000;c->edi=123;c->ecx=123;
unsigned views[]={1,3,18,20,0xffffffff};unsigned distances[]={0x466a6000,0x43c00000,0x42c80000,0x43c00000,0x466a6000};
for(unsigned i=0;i<5;i++){
 MR32(0x6004)=views[i];MR32(c->esp)=0x466a6000;assert(mw_hdreflections_hook(c,0x6e73ab));
 assert(MR32(c->esp)==distances[i]&&c->ecx==123);assert(c->zf==(views[i]==3||views[i]==20));
 MR32(0x982a20)=0x7000;MR32(0x7004)=2;MR32(0x9195e4+2*0x70)=views[i];MRF32(0x8f935c)=2;
 c->top=4;c->st[4]=2;assert(mw_hdreflections_hook(c,0x6db5c4));
 assert(c->top==4&&c->eax==views[i]&&c->st[4]==((views[i]==3||(int32_t)views[i]>=18)?.5:2));
}
CPU before=*c;mw_hdreflections_hook(c,0x6def3d);assert(MR32(0x8fae6c)==3&&!memcmp(c,&before,sizeof *c));
mw_hdreflections_hook(c,0x6def42);assert(MR32(0x8fae6c)==2&&!memcmp(c,&before,sizeof *c));
''')
if __name__=='__main__':unittest.main()
