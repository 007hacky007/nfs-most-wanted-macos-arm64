from pathlib import Path
import hashlib
import re
import subprocess
import tempfile
import unittest
from unittest import mock


RUNTIME_SHA='80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'
RUNTIME_CANDIDATES=(Path('out/installed/.nfsmw/runtime.exe'),
                    Path('game/.nfsmw/runtime.exe'),Path('game/speed.exe'))


def find_runtime_image(candidates=None):
    for path in RUNTIME_CANDIDATES if candidates is None else candidates:
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest()==RUNTIME_SHA:return path
        except OSError:
            continue
    return None


class WidescreenTests(unittest.TestCase):
    def runtime_image(self):
        image=find_runtime_image()
        if image is None:self.skipTest('requires SHA-verified 807 runtime image')
        return image

    def asset_path(self,path):
        path=Path(path)
        try:
            if path.is_file():
                with path.open('rb'):return path
        except OSError:
            pass
        self.skipTest(f'requires readable optional asset: {path}')

    def asset_text(self,path):
        try:return self.asset_path(path).read_text()
        except OSError:self.skipTest(f'requires readable optional asset: {path}')

    def test_registry_graphics_defaults_require_enabled_initialized_settings_file(self):
        body='''uint32_t value=0xabcdef;assert(!ws_registry_default("g_PerformanceLevel",&value)&&value==0xabcdef);
ws_configure(".");assert(!ws_registry_default("g_PerformanceLevel",&value));assert(ws_patch_init());
const char *names[]={"g_CarEnvironmentMapEnable","g_CarEnvironmentMapUpdateData","g_RoadReflectionEnable","g_MotionBlurEnable","g_ParticleSystemEnable","g_WorldLodLevel","g_CarLodLevel","g_OverBrightEnable","g_FSAALevel","g_RainEnable","g_TextureFiltering","g_RacingResolution","g_PerformanceLevel","g_VSyncOn","g_ShadowDetail","g_VisualTreatment"};
const uint32_t expected[]={3,1,3,1,1,3,1,1,7,1,2,1,5,0,2,1};
for(unsigned i=0;i<16;i++){value=0xabcdef;assert(ws_registry_default(names[i],&value)==ENABLED);assert(value==(ENABLED?expected[i]:0xabcdef));}
value=0xabcdef;assert(ws_registry_default("G_PERFORMANCELEVEL",&value)==ENABLED&&value==(ENABLED?5:0xabcdef));
value=0xabcdef;assert(!ws_registry_default("unknown",&value)&&value==0xabcdef);assert(!ws_registry_default(NULL,&value)&&value==0xabcdef);assert(!ws_registry_default("g_PerformanceLevel",NULL));
'''
        for ini,enabled in ((None,0),('[MISC]\nWriteSettingsToFile=0\n',0),('[MISC]\nWriteSettingsToFile=1\n',1)):
            self.run_native(body.replace('ENABLED',str(enabled)),ini,fragments='int ws_registry_default(const char*,uint32_t*);\n')

    def test_supplied_historical_registry_default_table_and_gate_match_native_values(self):
        path=self.asset_path('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.asi')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'32a087267fe2b08ec1213666893502dfccad014654324edf5d8cffc22a611353')
        import capstone,pefile,struct
        pe=pefile.PE(str(path));base=pe.OPTIONAL_HEADER.ImageBase
        section=next(section for section in pe.sections if section.Name.startswith(b'.text'));data=section.get_data();start=base+section.VirtualAddress
        pattern=re.compile(bytes.fromhex('8bc483ec08c700')+b'(.{4})'+bytes.fromhex('c74004')+b'(.{4})'+bytes.fromhex('8bc4c700')+b'(.{4})'+bytes.fromhex('c74004')+b'(.{4})'+b'\xe8(.{4})',re.S)
        defaults={}
        for record in pattern.finditer(data):
            value,length,key,key_length=(struct.unpack('<I',record[n])[0]for n in range(1,5))
            if start+record.start()+38+struct.unpack('<i',record[5])[0]!=0x1000e880:continue
            name=pe.get_data(key-base,key_length).decode('ascii')
            if name.startswith('g_'):defaults[name]=int(pe.get_data(value-base,length).decode('ascii'))
        expected={'g_CarEnvironmentMapEnable':3,'g_CarEnvironmentMapUpdateData':1,'g_RoadReflectionEnable':3,'g_MotionBlurEnable':1,'g_ParticleSystemEnable':1,'g_WorldLodLevel':3,'g_CarLodLevel':1,'g_OverBrightEnable':1,'g_FSAALevel':7,'g_RainEnable':1,'g_TextureFiltering':2,'g_RacingResolution':1,'g_PerformanceLevel':5,'g_VSyncOn':0,'g_ShadowDetail':2,'g_VisualTreatment':1}
        self.assertEqual(defaults,expected)
        decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
        gate=list(decoder.disasm(pe.get_data(0x132cb,13),0x100132cb))
        self.assertEqual([(ins.mnemonic,ins.op_str)for ins in gate],[('cmp','byte ptr [ebp - 0x1865], 0'),('je','0x10013ab7')])
        store=next(decoder.disasm(pe.get_data(0xf30f,7),0x1000f30f));self.assertEqual((store.mnemonic,store.op_str),('setne','byte ptr [ebp - 0x1865]'))
        standard=self.asset_text('out/installed/scripts/NFSMostWanted.WidescreenFix.ini');full=self.asset_text('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini')
        for ini,enabled in ((standard,0),(full,1)):
            self.run_native('ws_configure(".");assert(ws_patch_init());uint32_t value=0;assert(ws_registry_default("g_PerformanceLevel",&value)==ENABLED&&value==(ENABLED?5:0));'.replace('ENABLED',str(enabled)),ini,fragments='int ws_registry_default(const char*,uint32_t*);\n')

    def test_runtime_finder_requires_hash_and_accepts_private_runtime_locations(self):
        self.assertTrue(callable(globals().get('find_runtime_image')))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);protected=root/'game/speed.exe';protected.parent.mkdir();protected.write_bytes(b'protected image')
            first=root/'out/installed/.nfsmw/runtime.exe';second=root/'game/.nfsmw/runtime.exe'
            image=b'verified runtime fixture'
            with mock.patch.dict(globals(),{'RUNTIME_SHA':hashlib.sha256(image).hexdigest()}):
                self.assertIsNone(find_runtime_image((protected,first,second)))
                for path in (first,second):
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(image)
                    self.assertEqual(find_runtime_image((protected,path)),path)
                    path.unlink()

    def test_left_deadzone_raw_boundaries_without_game_assets(self):
        self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esi=0x5000;c->ebp=0x9000;c->esp=0x8000;c->cf=c->zf=c->of=1;c->top=4;c->st[4]=1.25;
unsigned raw[]={29490,29491,32767,32768,36044,36045},expected[]={29490,32767,32767,32767,32767,36045};
for(unsigned i=0;i<6;i++){c->eax=raw[i];c->edx=raw[5-i];MR32(0x5234)=c->eax;MR32(0x5238)=c->edx;CPU before=*c;assert(ws_hook(c,0x7f29b8)&&ws_hook(c,0x7f29ca));assert(MR32(0x5234)==expected[i]&&MR32(0x5238)==expected[5-i]);assert(!memcmp(c,&before,sizeof *c));}
''','[MISC]\nLeftStickDeadzone=10\n')

    def test_enabled_splash_filename_replacement_preserves_full_hud_mode_zero(self):
        image=self.runtime_image()
        import pefile
        game=pefile.PE(str(image))
        wide=game.get_data(0x89f828-0x400000,20);normal=game.get_data(0x8a0114-0x400000,20)
        self.assertEqual(wide,b'WS_MW_LS_Splash.fng\0');self.assertEqual(normal.split(b'\0')[0],b'MW_LS_Splash.fng')
        for ini,enabled in ((self.asset_text('out/installed/scripts/NFSMostWanted.WidescreenFix.ini'),1),(self.asset_text('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini'),0),('[MAIN]\nFixHUD=0\nHudAspectRatioConstraint=Auto\n',0)):
            self.run_native('''memcpy(g_mem+0x89f828,"WS_MW_LS_Splash.fng",20);memcpy(g_mem+0x8a0114,"MW_LS_Splash.fng",16);MR8(0x8a0127)=0xa5;MR8(0x8a0128)=0x5a;
ws_configure(".");assert(ws_patch_init());assert(!strcmp((char*)g_mem+0x8a0114,ENABLED?"WS_MW_LS_Splash.fng":"MW_LS_Splash.fng"));assert(MR8(0x8a0127)==(ENABLED?0:0xa5)&&MR8(0x8a0128)==0x5a);
'''.replace('ENABLED',str(enabled)),ini)

    def test_splash_branch_uses_real_conditional_instruction_without_flag_changes(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image),branch_hooks={0x5a3080:0x5a3082});code,_=lifter.lift(0x5a3080)
        fragments='int guest_branch(CPU*c,uint32_t address){return ws_branch(c,address)>0; }\n'+code[:code.index('L_005a3082:')]+'''L_005a3082:c->eip=0x5a3082;return;
L_005a30a2:c->eip=0x5a30a2;return;}\n'''
        for ini,enabled in (('[MAIN]\nFixHUD=1\nHudAspectRatioConstraint=Auto\n',1),('[MAIN]\nHUDWidescreenMode=0\n',0)):
            self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=0x1234;c->cf=1;c->top=4;c->st[4]=1.25;
for(unsigned zero=0;zero<2;zero++){c->zf=zero;CPU before=*c;sub_005a3080(c);assert(c->eip==(ENABLED||!zero?0x5a3082:0x5a30a2));c->eip=before.eip;assert(!memcmp(c,&before,sizeof *c));}
'''.replace('ENABLED',str(enabled)),ini,fragments)

    def test_splash_prompt_uses_live_three_argument_slots_and_original_cleanup(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image));fragments='''static uint32_t expected_start,expected_click,prompt_calls;
void sub_00525220(CPU*c){assert(MR32(c->esp+4)==0x6000&&MR32(c->esp+8)==expected_click&&MR32(c->esp+12)==expected_start);prompt_calls++;POP32(c->eip);c->eax=0xabcdef;}
void prompt(CPU*c){\n'''
        for instruction in lifter.md.disasm(lifter.TDATA[0x5a313c-lifter.TVA:0x5a314f-lifter.TVA],0x5a313c):
            if instruction.address in (0x5a3141,0x5a3146):fragments+=f'ws_hook(c,{instruction.address:#x});\n'
            fragments+='\n'.join(lifter.insn(instruction,set()))+'\n'
        fragments+='}\n'
        for ini,start,click in ((self.asset_text('out/installed/scripts/NFSMostWanted.WidescreenFix.ini'),0xd18d4c4c,0xc4df3ff2),(self.asset_text('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini'),0x9b580b7e,0xc6cc55a4)):
            self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->ecx=0x6000;c->ebp=0x9000;c->esi=0x5000;c->ebx=7;c->edi=11;c->top=4;c->st[4]=1.25;expected_start=START;expected_click=CLICK;
for(unsigned i=0;i<14;i++)MR32(0x8000+i*4)=0x70000000+i;
prompt(c);assert(prompt_calls==1&&c->esp==0x8038&&c->eax==0xabcdef&&c->ecx==0x6000&&c->ebp==0x9000&&c->esi==0x5000&&c->ebx==7&&c->edi==11&&c->top==4&&c->st[4]==1.25);
for(unsigned i=0;i<14;i++)assert(MR32(0x8000+i*4)==0x70000000+i);
'''.replace('START',hex(start)).replace('CLICK',hex(click)),ini,fragments)

    def test_gaming_logo_replacement_calls_original_show_with_one_live_argument(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image),branch_hooks={0x5a30b1:0x5a30b6})
        code,_=lifter.lift(0x5a30b0)
        fragments='int guest_branch(CPU*c,uint32_t address){return ws_branch(c,address)>0; }\n'
        for entry in (0x514c70,0x514cc0):fragments+=lifter.lift(entry)[0]
        fragments+=code[:code.index('    /* 005a30b9')]+ 'return;}\n'
        for ini,expected in (('[MAIN]\nFixHUD=1\nHudAspectRatioConstraint=Auto\n',0x2400000),('[MAIN]\nHUDWidescreenMode=0\n',0x2400001)):
            self.run_native('''ws_configure(".");assert(ws_patch_init());logo_engine=sub_00514cc0;CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=0x60000;c->esi=0x5000;c->ebp=0x9000;c->ebx=7;c->edi=11;c->top=4;c->st[4]=1.25;
MR32(0x60018)=5;MR32(0x60060)=2;MR32(0x60064)=0x61000;MR32(0x61004)=0x62000;MR32(0x61018)=MR32(0x62018)=1;
MR32(0x6001c)=MR32(0x6101c)=MR32(0x6201c)=1;MR32(0x8000)=0x2000;MR32(0x8004)=0x534cc377;sub_005a30b0(c);
assert(MR32(0x6001c)==EXPECTED&&MR32(0x6101c)==EXPECTED&&MR32(0x6201c)==EXPECTED&&c->esp==0x8008&&MR32(0x8000)==0x2000&&MR32(0x8004)==0x534cc377&&c->esi==0x5000&&c->ebp==0x9000&&c->ebx==7&&c->edi==11&&c->top==4&&c->st[4]==1.25);
'''.replace('EXPECTED',hex(expected)),ini,fragments)

    def test_missing_controller_texture_rejects_initialization(self):
        self.run_native('ws_configure(".");assert(!ws_patch_init()&&!visitor_callback);','[MISC]\nImproveGamepadSupport=1\n',asset=False)
        self.run_native('ws_configure(".");assert(ws_patch_init()&&!visitor_callback);','[MISC]\nImproveGamepadSupport=0\n',asset=False)

    def test_stick_click_pulse_preserves_host_q_and_real_buffered_events(self):
        self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esi=0x5000;
MR32(0x5260)=MR32(0x5264)=1;MR32(0x925e90)=3;
uint32_t first=kbd_ev_head();assert(ws_hook(c,0x7f2ae9));assert(!kbd_key_down(0x10));
KbdEv event;assert(kbd_ev_head()==first+2&&kbd_ev_get(first,&event)==1&&event.dik==0x10&&event.down);assert(kbd_ev_get(first+1,&event)==1&&!event.down);kbd_pump();assert(message_calls==3);
kbd_set_key(KSRC_HOST,0x10,1);first=kbd_ev_head();assert(ws_hook(c,0x7f2ae9));assert(kbd_key_down(0x10)&&kbd_ev_head()==first);kbd_pump();assert(message_calls==6);
kbd_release_source(KSRC_HOST);assert(!kbd_key_down(0x10));
MR32(0x925e90)=4;first=kbd_ev_head();assert(ws_hook(c,0x7f2ae9));assert(kbd_ev_head()==first);kbd_pump();assert(message_calls==6);
''','[MISC]\nImproveGamepadSupport=1\n','''#include "kbd.h"
uint32_t host_ms(void){return 123;}
int win32_msg_room(void){return 100;}
void win32_post_message(uint32_t message,uint32_t wp,uint32_t lp){
assert(wp==(message==0x102?'q':0x51));assert(message==0x100||message==0x101||message==0x102);
assert(lp==(message==0x101?0xc0100001u:0x00100001u));message_calls++;
}
''',keyboard=True)

    def test_icon_mapping_matches_actual_supplied_callback_instructions(self):
        path=self.asset_path('out/installed/.nfsmw/windows/widescreen/scripts/NFSMostWanted.WidescreenFix.asi')
        from tools.lift import Lifter, CC
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'f3a7f8c04db295154e10987303a7237a8dc70e2ba944d38a79f895ad1f570dd1')
        lifter=Lifter(str(path));instructions=list(lifter.md.disasm(lifter.TDATA[0x1003a3ba-lifter.TVA:0x1003a42a-lifter.TVA],0x1003a3ba))
        # Actual compiled image path, after the one-time resource loader and
        # before the stack/security-cookie epilogue. Invalid-parameter INT29 is
        # unreachable for these pinned valid mode/hash inputs.
        fragments='void supplied_icons(CPU*c){\n'
        for instruction in instructions:
            fragments+=f'L_{instruction.address:08x}:;\n'
            if instruction.mnemonic.startswith('j'):
                condition='' if instruction.mnemonic=='jmp' else f'if({CC[instruction.mnemonic[1:]]}) '
                fragments+=condition+f'goto L_{instruction.operands[0].imm:08x};\n'
            elif instruction.mnemonic=='int':fragments+='__builtin_trap();\n'
            else:fragments+='\n'.join(lifter.insn(instruction,set()))+'\n'
        fragments+='L_1003a42a:return;}\n'
        fragments+='static uint32_t hash(const char*s){uint32_t h=0xffffffffu;while(*s)h=(unsigned char)*s++ +33*h;return h;}\n'
        self.run_native('''free(g_mem);g_mem=calloc(1,0x11000000);ws_configure(".");assert(ws_patch_init());
const char *names[]={"L1","PC_KEY_Q","PC_GREATERTHAN_LESSTHAN","R1","PC_KEY_ENTER","PC_KEY_ESC_FRENCH","PC_KEY_ESC","PC_KEY_1","PC_KEY_2","PC_KEY_3","PC_KEY_4","PC_ARROW_KEYS_UP_DOWN","PC_LOAD","PC_ARROW_KEYS"};
for(unsigned i=0;i<14;i++){char text[64];MR32(0x5000+i*12)=hash(names[i]);const char*suffix=!strncmp(names[i],"PC_",3)?names[i]+3:names[i];snprintf(text,sizeof text,"XBOX_%s",suffix);MR32(0x5004+i*12)=hash(text);snprintf(text,sizeof text,"PS_%s",suffix);MR32(0x5008+i*12)=hash(text);}
MR32(0x101f2c54)=0x5000;MR32(0x101f2c58)=0x5000+14*12;MR32(0x101f2b7c)=1;
for(unsigned pad=0;pad<2;pad++)for(unsigned icon=0;icon<14;icon++)for(unsigned old=0;old<3;old++){
 CPU cpu={0},*c=&cpu;c->esp=0x8000;c->ebp=0x9000;MR32(c->ebp-0x13c+12)=MR32(c->ebp-0x13c+16)=32768;
 MR8(c->ebp-0x13c+48)=pad?0x80:0;ws_hook(c,0x7f2981);if(!pad){MR8(c->ebp-0x130)=0x80;ws_hook(c,0x7f21cf);}MR8(0x101f2b78)=pad;
 unsigned handle=MR32(0x5000+icon*12+old*4);MR32(0x60018)=MR32(0x61018)=1;MR32(0x60024)=MR32(0x61024)=handle;MR32(0x6001c)=MR32(0x6101c)=0x20;
 c->edi=0x60000;supplied_icons(c);c->esp=0x8000;MR32(c->esp)=0x123456;MR32(c->esp+4)=0x61000;visitor_callback(c);
 assert(c->eax==1&&c->esp==0x8008&&c->eip==0x123456);assert(MR32(0x60024)==MR32(0x61024)&&MR32(0x6001c)==MR32(0x6101c));
}
''','[MISC]\nImproveGamepadSupport=1\n',fragments)

    def test_controller_buttons_labels_menu_and_start_hashes(self):
        for mode in (1,2):
            self.run_native('''ws_configure(".");assert(ws_patch_init());
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;c->ebp=0x9000;c->eax=0x12345;c->cf=c->zf=1;c->top=4;c->st[4]=128;CPU before=*c;
MR32(0x5258)=MR32(0x5248)=MR32(0x525c)=1;MR32(0x5260)=MR32(0x5264)=1;MR32(0x925e90)=3;
assert(ws_hook(c,0x7f2ae9));assert(!memcmp(c,&before,sizeof *c));
assert(MR32(0x8f3514)==1&&MR32(0x8f3584)==1&&MR32(0x8f34f8)==1&&key_calls==2&&message_calls==3);
memset(g_mem+0x5234,0,52);assert(ws_hook(c,0x7f2ae9));assert(!MR32(0x8f3514)&&!MR32(0x8f3584)&&!MR32(0x8f34f8)&&key_calls==2);
MR32(c->esp+4)=0x6000;strcpy((char*)g_mem+0x6000,"Joystick Button 10");assert(ws_hook(c,0x6282d3));assert(!strcmp((char*)g_mem+0x6000,MODE==2?"R3":"Right stick")&&!memcmp(c,&before,sizeof *c));
strcpy((char*)g_mem+0x6000,"Joystick X Rotation");assert(ws_hook(c,0x6282d3));assert(!strcmp((char*)g_mem+0x6000,"Right stick Left/Right"));
assert(ws_branch(c,0x628a52));assert(c->st[4]==1&&c->top==4&&c->cf==1&&c->zf==1);assert(MR32(0x91fabc)==0&&MR32(0x91faf0)==1&&MR32(0x91fc90)==3);
assert(ws_hook(c,0x5a3141));assert(MR32(c->esp)==(MODE==2?0xdc64c04c:0xd18d4c4c));
'''.replace('MODE',str(mode)),f'[MISC]\nImproveGamepadSupport={mode}\n')

    def test_controller_icons_use_actual_recursive_visitor_and_input_switches(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image));fragments=''
        for entry in (0x5b1510,0x5b1560):fragments+=lifter.lift(entry)[0]
        fragments='''guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
void dispatch_indirect(CPU*c,uint32_t target){assert(target==0xc1000000u&&visitor_callback);visitor_callback(c);}
static uint32_t hash(const char*s){uint32_t h=0xffffffffu;while(*s)h=(unsigned char)*s++ +33*h;return h;}
'''+fragments
        self.run_native('''
ws_configure(".");assert(ws_patch_init());assert(visitor_callback);visitor_engine=sub_005b1560;
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->ecx=0x10000;c->ebp=0x9000;c->esi=0x5000;c->top=4;c->st[4]=1.25;CPU before=*c;
MR32(0x100e0)=0x20000;MR32(0x2004c)=0x30000;MR32(0x30018)=5;MR32(0x30064)=0x40000;
const char *names[]={"L1","PC_KEY_Q","PC_GREATERTHAN_LESSTHAN","R1","PC_KEY_ENTER","PC_KEY_ESC_FRENCH","PC_KEY_ESC","PC_KEY_1","PC_KEY_2","PC_KEY_3","PC_KEY_4","PC_ARROW_KEYS_UP_DOWN","PC_LOAD","PC_ARROW_KEYS"};
for(unsigned i=0;i<14;i++){unsigned object=0x40000+0x100*i;MR32(object+4)=i<13?object+0x100:0;MR32(object+0x18)=1;MR32(object+0x24)=hash(names[i]);}
unsigned state=c->ebp-0x13c;MR32(state)=MR32(state+4)=MR32(state+12)=MR32(state+16)=32768;MR8(state+48)=0x80;
assert(ws_hook(c,0x7f2981));assert(ws_hook(c,0x5c53c0));assert(!memcmp(c,&before,sizeof *c)&&tpk_loads==1);
for(unsigned i=0;i<14;i++){char text[64];snprintf(text,sizeof text,"XBOX_%s",!strncmp(names[i],"PC_",3)?names[i]+3:names[i]);assert(MR32(0x40024+0x100*i)==hash(text)&&MR32(0x4001c+0x100*i)==0x2400000);}
/* A keyboard event switches every known icon back, including nested images. */
MR8(c->ebp-0x130+7)=0x80;assert(ws_hook(c,0x7f21cf));assert(ws_hook(c,0x5c53c0));assert(tpk_loads==1&&!memcmp(c,&before,sizeof *c));
for(unsigned i=0;i<14;i++)assert(MR32(0x40024+0x100*i)==hash(names[i]));
''','[MISC]\nImproveGamepadSupport=1\n',fragments)

    def test_hud_layout_flags_and_resize_refresh_match_selected_preset(self):
        for ini,mode in (('[MAIN]\nHudAspectRatioConstraint=Auto\n',1),('[MAIN]\nHUDWidescreenMode=0\n',0)):
            self.run_native('''
ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;c->eax=0x123400ff;c->ecx=1;c->edx=1;c->zf=c->cf=1;
MR32(0x5024)=0x2000;MRF32(0x3000)=100;MRF32(0x4000)=200;ws_set_resolution(1920,1080);
assert(ws_hook(c,0x5696ce));assert(c->eax==0x12340000+MODE);
c->eax=0x123400ff;assert(ws_hook(c,0x58d886));assert(c->eax==0x12340000+MODE);
assert(ws_hook(c,0x57cb85));assert(c->zf==(MODE==1));
assert(ws_hook(c,0x56885d));assert(c->zf==(MODE==1));
'''.replace('MODE',str(mode)),ini)
        self.run_native('''
ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;
MR32(0x5024)=0x2000;MRF32(0x3000)=100;MRF32(0x4000)=200;MR8(0x5330)=1;
ws_set_resolution(1920,1080);assert(ws_hook(c,0x5696ce));float first=MRF32(0x3000);unsigned calls=fe_calls;
assert(ws_hook(c,0x5696ce));assert(fe_calls==calls&&MRF32(0x3000)==first);
ws_set_resolution(1600,1200);assert(ws_hook(c,0x5696ce));assert(fe_calls>calls&&MRF32(0x3000)==100&&MRF32(0x4000)==200);
''','[MAIN]\nHudAspectRatioConstraint=Auto\n')

    def test_camera_stick_binding_pitch_limits_and_mouse_consumption(self):
        self.run_native('''
ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;c->ebp=0x9000;
MR32(c->esp+4)=0x10100;MR32(c->esp+8)=0x10200;MRF32(0x988dec)=0;
MR32(0x509c)=2;ws_hook(c,0x47d416);unsigned state=c->ebp-0x13c;MR32(state)=MR32(state+4)=32768;MR32(state+12)=MR32(state+16)=65535;
assert(ws_hook(c,0x7f2981));MRF32(0x10100)=10;MRF32(0x10104)=MRF32(0x10108)=0;
assert(ws_hook(c,0x47dcbc));assert(fabsf(MRF32(0x10104)+10*cosf(.0174533f)*sinf(.0174533f))<.00001f);
assert(fabsf(MRF32(0x10108)-10*sinf(.0174533f))<.00001f);
/* A game action bound to the right stick suppresses both axes. */
MR32(0x509c)=1;ws_hook(c,0x47d416);ws_hook(c,0x47dcbc);MR32(0x509c)=2;ws_hook(c,0x47d416);MR32(0x91f41c)=6;
MRF32(0x10100)=10;MRF32(0x10104)=MRF32(0x10108)=0;ws_hook(c,0x47dcbc);assert(MRF32(0x10100)==10&&MRF32(0x10104)==0&&MRF32(0x10108)==0);
/* Mouse remains usable and clamps its positive pitch offset at60deg. */
MR32(c->ebp-0x14)=0;MR32(c->ebp-0x10)=1000;MR32(c->ebp-0xc)=0;ws_hook(c,0x7f201d);ws_hook(c,0x47dcbc);
assert(fabsf(MRF32(0x10108)-10*sinf(60*.0174533f))<.00001f);
MRF32(0x10100)=10;MRF32(0x10104)=MRF32(0x10108)=0;ws_hook(c,0x47dcbc);assert(fabsf(MRF32(0x10108)-10*sinf(60*.0174533f))<.00001f);
''','[CAMERA]\nEnable=1\n')

    def test_camera_cursor_deadline_and_real_cdecl_return_frame(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image),branch_hooks={0x56fdb0:0x570561})
        code,_=lifter.lift(0x56fdb0)
        # Keep the actual native-edge/RET instructions; the original cursor
        # renderer is deliberately outside this headless deadline fixture.
        prefix=code[:code.index('    PUSH32(c->ebp);')];tail=code[code.index('L_00570561:'):]
        fragments='''#include <time.h>
static uint64_t now=1000000000;static unsigned original_cursor;
int clock_gettime(clockid_t clock,struct timespec*t){assert(clock==CLOCK_MONOTONIC);t->tv_sec=now/1000000000;t->tv_nsec=now%1000000000;return 0;}
int guest_branch(CPU*c,uint32_t site){return ws_branch(c,site);}
'''+prefix+'original_cursor++;return;\n'+tail
        self.run_native('''
ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;
MR32(0x509c)=1;ws_hook(c,0x47d416);ws_hook(c,0x47dcbc);CPU before=*c;
MR32(c->esp)=0x123456;MR32(c->esp+4)=17;MR32(c->esp+8)=23;now+=99999999;
sub_0056fdb0(c);assert(!original_cursor&&c->esp==before.esp+4&&c->eip==0x123456&&MR32(c->esp)==17&&MR32(c->esp+4)==23);
*c=before;now++;assert(!ws_branch(c,0x56fdb0));sub_0056fdb0(c);assert(original_cursor==1&&!memcmp(c,&before,sizeof *c));
''','[CAMERA]\nEnable=1\n',fragments)

    def test_unfiltered_pad_snapshot_precedes_guest_left_filter_and_keeps_right_axes(self):
        # Compile the production DirectInput range conversion, rather than a
        # test reimplementation, together with real gamepad_read().
        source=Path('runtime/dinput_pad.c').read_text()
        conversion=source[source.index('static int32_t scale_axis('):source.index('static uint32_t pov_of(')]
        fragments='''#include "gamepad.h"
typedef struct {uint32_t dz[8],sat[8];int32_t mn[8],mx[8];} Dev;
'''+conversion
        self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;c->ebp=0x9000;
Dev device={0};for(unsigned i=0;i<8;i++){device.sat[i]=10000;device.mx[i]=65535;}
gamepad_synth_connect(1);gamepad_synth_axis(PAD_AXIS_LX,(34000.f-32768.f)/32767.f);gamepad_synth_axis(PAD_AXIS_RX,.03f);
PadState pad;assert(gamepad_read(&pad));unsigned left=scale_axis(pad.axis[PAD_AXIS_LX],&device,0),right=scale_axis(pad.axis[PAD_AXIS_RX],&device,2);assert(left==34000&&right>32768);
unsigned state=c->ebp-0x13c;MR32(state)=left;MR32(state+4)=MR32(state+16)=32768;MR32(state+12)=right;
assert(ws_hook(c,0x7f2981));assert(MR32(state)==left&&MR32(state+12)==right);
c->eax=left;MR32(c->esi+0x234)=c->eax;CPU before=*c;assert(ws_hook(c,0x7f29b8));assert(MR32(c->esi+0x234)==32767&&!memcmp(c,&before,sizeof *c));
/* Icon detection uses the pre-filter left value, which exceeds1% even though
 * the later left-store deadzone removes this3.76% input. */
MR32(0x60018)=1;MR32(0x60024)=0x000005bc; /* bStringHash("L1") */
MR32(c->esp)=0x123456;MR32(c->esp+4)=0x60000;visitor_callback(c);assert(MR32(0x60024)==0x297ef63cu); /* XBOX_L1 */
''','[MISC]\nImproveGamepadSupport=1\nLeftStickDeadzone=10\nRightStickDeadzone=10\n',fragments,gamepad=True)

    def test_historical_full_leaves_native_right_filter_and_raw_state_dormant(self):
        self.run_native('''ws_configure(".");assert(ws_patch_init()&&!visitor_callback);gamepad_synth_connect(1);
gamepad_synth_axis(PAD_AXIS_LX,.03f);gamepad_synth_axis(PAD_AXIS_RX,.03f);PadState pad;assert(gamepad_read(&pad));assert(pad.axis[PAD_AXIS_LX]==.03f&&pad.axis[PAD_AXIS_RX]==0);
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->ebp=0x9000;c->esi=0x5000;c->eax=0x12345678;c->cf=c->zf=1;unsigned state=c->ebp-0x13c;for(unsigned i=0;i<20;i++)MR32(state+4*i)=0x12340000+i;
unsigned raw[20];memcpy(raw,g_mem+state,sizeof raw);CPU before=*c;assert(ws_hook(c,0x7f2981));assert(!memcmp(c,&before,sizeof *c)&&!memcmp(raw,g_mem+state,sizeof raw));
''','[MISC]\nImproveGamepadSupport=0\nLeftStickDeadzone=10\n','#include "gamepad.h"\n',gamepad=True)

    def test_left_deadzone_applies_after_canonical_stores_at_raw_boundaries(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image));fragments=''
        for site,hook in ((0x7f29b2,0x7f29b8),(0x7f29c4,0x7f29ca)):
            instruction=next(lifter.md.disasm(lifter.TDATA[site-lifter.TVA:hook-lifter.TVA],site))
            self.assertEqual(instruction.mnemonic,'mov');self.assertEqual(instruction.address+instruction.size,hook)
            fragments+=f'void store_{site:x}(CPU*c){{'+''.join(lifter.insn(instruction,set()))+f'ws_hook(c,{hook:#x});}}\n'
        for path in ('out/installed/scripts/NFSMostWanted.WidescreenFix.ini','out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini'):
            self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esi=0x5000;c->ebp=0x9000;c->esp=0x8000;c->cf=c->zf=c->of=1;c->top=4;c->st[4]=1.25;
unsigned raw[]={29490,29491,32767,32768,36044,36045},expected[]={29490,32767,32767,32767,32767,36045};
for(unsigned i=0;i<6;i++){c->eax=raw[i];c->edx=raw[5-i];CPU before=*c;store_7f29b2(c);store_7f29c4(c);assert(MR32(0x5234)==expected[i]&&MR32(0x5238)==expected[5-i]);assert(!memcmp(c,&before,sizeof *c));}
''',self.asset_text(path),fragments)
        # A disabled source hook leaves the original raw MOV unchanged.
        self.run_native('''ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esi=0x5000;c->eax=c->edx=32768;store_7f29b2(c);store_7f29c4(c);assert(MR32(0x5234)==32768&&MR32(0x5238)==32768);
''','[MISC]\nLeftStickDeadzone=0\n',fragments)

    def test_ws_disables_host_filtering_only_for_owned_sticks(self):
        for path,right in (('out/installed/scripts/NFSMostWanted.WidescreenFix.ini',0),('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini',-1)):
            self.run_native('''
ws_configure(".");assert(ws_patch_init());assert(dz_calls==1&&selected_left==0&&fabsf(selected_right-(RIGHT))<.000001f);
'''.replace('RIGHT',str(right)),self.asset_text(path))

    def test_camera_orbit_and_idle_return_follow_original_view_target(self):
        self.run_native('''
ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;c->ebp=0x9000;c->top=4;c->st[4]=1.25;
MR32(0x509c)=2;MR8(0x50a1)=0;assert(ws_hook(c,0x47d416));
MR32(c->esp)=0x10000;MR32(c->esp+4)=0x10100;MR32(c->esp+8)=0x10200;MR32(c->esp+12)=0x10300;
MRF32(0x988dec)=1;MRF32(0x10100)=10;MRF32(0x10104)=MRF32(0x10108)=0;memset(g_mem+0x10200,0,12);
MR32(c->ebp-0x14)=(uint32_t)-20;MR32(c->ebp-0x10)=MR32(c->ebp-0xc)=0;assert(ws_hook(c,0x7f201d));
CPU before=*c;assert(ws_hook(c,0x47dcbc));assert(!memcmp(c,&before,sizeof *c));
assert(fabsf(MRF32(0x10100)-10*cosf(3*.0174533f))<.00001f&&fabsf(MRF32(0x10104)-10*sinf(3*.0174533f))<.00001f);
for(unsigned i=1;i<=3;i++){
 MRF32(0x10200)=2.f*i;MRF32(0x10100)=2.f*i+10;MRF32(0x10104)=MRF32(0x10108)=0;
 assert(ws_hook(c,0x47dcbc));float yaw=i<3?3.f:3.f*expf(-2.f);
 assert(fabsf(MRF32(0x10100)-(2.f*i+10*cosf(yaw*.0174533f)))<.00001f);
 assert(fabsf(MRF32(0x10104)-10*sinf(yaw*.0174533f))<.00001f);
}
MR8(0x50a1)=1;ws_hook(c,0x47d416);MRF32(0x10100)=99;MRF32(0x10104)=7;
assert(ws_hook(c,0x47dcbc));assert(MRF32(0x10100)==99&&MRF32(0x10104)==7);
''','[CAMERA]\nEnable=1\n')

    def test_auto_hud_groups_cache_original_positions_and_follow_physical_aspect(self):
        self.run_native('''
ws_configure(".");assert(ws_patch_init());assert(fe_allocations==1);ws_set_resolution(1920,1080);
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->esi=0x5000;c->eax=55;c->zf=c->cf=1;c->top=4;c->st[4]=1.25;
MR32(0x5024)=0x2000;MRF32(0x3000)=100;MRF32(0x3004)=25;MRF32(0x4000)=200;MRF32(0x4004)=35;CPU before=*c;
for(unsigned i=0;i<2;i++){
 assert(ws_hook(c,i?0x569717:0x5696f6));assert(!memcmp(c,&before,sizeof *c));
 assert(fabsf(MRF32(0x3000)-(100-(240.f*(16.f/9.f)-320)))<.0001f);
 assert(fabsf(MRF32(0x4000)-(200+(240.f*(16.f/9.f)-320)))<.0001f);
 assert(MRF32(0x3004)==25&&MRF32(0x4004)==35);
}
ws_set_resolution(1600,1200);assert(ws_hook(c,0x5696f6));assert(MRF32(0x3000)==100&&MRF32(0x4000)==200);
fe_absent=1;unsigned calls=fe_calls;assert(ws_hook(c,0x569717));assert(fe_calls==calls+2&&!memcmp(c,&before,sizeof *c));
''','[MAIN]\nHudAspectRatioConstraint=Auto\n')

    def test_auto_minimap_positions_are_idempotent_and_keep_original_stack(self):
        self.run_native('''
ws_configure(".");assert(ws_patch_init());ws_set_resolution(1920,1080);
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->ecx=0x10000;c->eax=17;c->zf=1;c->top=4;c->st[4]=1.25;
unsigned offsets[]={60,64,68,72,144};
for(unsigned i=0;i<5;i++){MR32(c->ecx+offsets[i])=0x11000+64*i;MR32(0x11000+64*i+44)=0x12000+64*i;MRF32(0x12000+64*i+28)=10.f*i;}
MRF32(0x100b8)=100;MR32(0x100bc)=0x12345678;CPU before=*c;
for(unsigned wide=0;wide<2;wide++)for(unsigned repeat=0;repeat<2;repeat++){
 MR32(c->esp+4)=wide;assert(ws_branch(c,0x5678a0)==1);assert(!memcmp(c,&before,sizeof *c));
 float offset=(wide?-1.f:1.f)*(240.f*(16.f/9.f)-320);
 assert(fabsf(MRF32(0x100b8)-(100+offset))<.0001f);
 for(unsigned i=0;i<5;i++)assert(fabsf(MRF32(0x12000+64*i+28)-(10.f*i+offset))<.0001f);
 assert(fabsf(MRF32(0x91cf04)-(wide?offset:0))<.0001f&&MRF32(0x91cf0c)==(wide?-.9375f:.9375f));
 assert(MR32(0x12120)==0x12345678);
}
''','[MAIN]\nHudAspectRatioConstraint=Auto\n')

    def test_x360_shadow_distance_operand_is_applied_once(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        canonical=Lifter(str(image));canonical.fafter={};canonical.entry=0x6c9653
        captured=Path('work/hq-module/out/full-start5/captures/0006-late.game.bin')
        if not captured.is_file():self.skipTest('requires captured supplied X360 game patch')
        patched=captured.read_bytes()[0x6c9653-0x400000:0x6c9659-0x400000]
        self.assertEqual(patched,bytes.fromhex('d80dd0f00201'))
        fragments=''
        stock=canonical.TDATA[0x6c9653-canonical.TVA:0x6c9659-canonical.TVA]
        original=next(canonical.md.disasm(stock,0x6c9653))
        self.assertEqual((original.mnemonic,original.op_str,original.size),('fmul','dword ptr [0x8910c4]',6))
        for name,data in (('stock',stock),('x360',patched)):
            instruction=next(canonical.md.disasm(data,0x6c9653))
            fragments+=f'void shadow_{name}(CPU*c){{'+''.join(canonical.insn(instruction,set()))+'ws_hook(c,0x6c9659);}\n'
        self.run_native('''
free(g_mem);g_mem=calloc(1,0x1100000);assert(g_mem);CPU cpu={0},*c=&cpu;c->top=4;c->st[4]=1.25;
MRF32(0x8910c4)=1.1f;MRF32(0x0102f0d0)=10;
MR32(0x6c9655)=0x8910c4;shadow_stock(c);assert(fabs(c->st[4]-12.5)<.000001);
c->st[4]=1.25;MR32(0x6c9655)=0x0102f0d0;shadow_x360(c);assert(fabs(c->st[4]-12.5)<.000001&&c->top==4);
''',fragments=fragments)


    def test_selected_postfx_event_preserves_cpu_and_historical_full_defaults(self):
        standard=self.asset_text('out/installed/scripts/NFSMostWanted.WidescreenFix.ini')
        full=self.asset_text('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini')
        for ini,gamma,border,calls in ((standard,1,2,1),(full,0,0,0),('[GRAPHICS]\nConsoleGamma=9\nHideAABug=-3\n',2,0,1)):
            self.run_native('''
free(g_mem);g_mem=calloc(1,0x1000000);ws_configure(".");assert(ws_patch_init());
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=123;c->ecx=456;c->cf=c->zf=1;c->top=4;c->st[4]=1.25;CPU before=*c;
assert(ws_hook(c,0x6e75ac));assert(!memcmp(c,&before,sizeof *c));
assert(postfx_calls==CALLS&&postfx_gamma==GAMMA&&postfx_border==BORDER);
'''.replace('CALLS',str(calls)).replace('GAMMA',str(gamma)).replace('BORDER',str(border)),ini)

    def test_all_new_hooks_preserve_legacy_state_without_an_ini(self):
        stage=Path('runtime/mw_widescreen.c').read_text()
        legacy={0x4c41f9,0x6cf4f6,0x6cf56c,0x6cf57e,0x6cf5e2,0x6e466c,0x6e47f0,0x6e46b6,0x6e4836,
                0x6d4811,0x6d482f,0x6c9659,0x6c9c4b,0x6d4c21,0x59a03f,0x591460}
        sites={int(value,16) for value in re.findall(r'HOOK_SITE\((0x[0-9a-f]+)\)',stage)}-legacy
        branches=re.findall(r'HOOK_BRANCH\((0x[0-9a-f]+)',stage)
        body='assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x1000;c->eax=123;c->cf=c->zf=1;CPU before=*c;\n'
        for site in sorted(sites):body+=f'assert(ws_hook(c,{site:#x})&&!memcmp(c,&before,sizeof *c));\n'
        for site in branches:body+=f'assert(!ws_branch(c,{site})&&!memcmp(c,&before,sizeof *c));\n'
        self.run_native(body)

    def test_canonical_shadow_and_simulation_instructions_keep_stack_layout(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),'80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        lifter=Lifter(str(image));lifter.fafter={};fragments=''
        source=Path('runtime/mw_widescreen.c').read_text()
        hooks={int(value,16) for value in re.findall(r'HOOK_SITE\((0x[0-9a-f]+)\)',source)}
        ranges=((0x6c8786,0x6c8791),(0x6c87b8,0x6c87c3),(0x6c86b0,0x6c86b5),
                (0x6c86c0,0x6c86c5),(0x6e5507,0x6e551b),(0x6de379,0x6de383),
                (0x6e5173,0x6e5178),(0x6bffa1,0x6bffa6),(0x6660ff,0x666104))
        for start,stop in ranges:
            lifter.entry=start;fragments+=f'void fragment_{start:x}(CPU*c){{\n'
            instructions=list(lifter.md.disasm(lifter.TDATA[start-lifter.TVA:stop-lifter.TVA],start))
            self.assertEqual(instructions[-1].address+instructions[-1].size,stop)
            for instruction in instructions:
                if instruction.address in hooks:fragments+=f'ws_hook(c,0x{instruction.address:x});\n'
                fragments+='\n'.join(lifter.insn(instruction,set()))+'\n'
            if stop in hooks:fragments+=f'ws_hook(c,0x{stop:x});\n'
            fragments+='}\n'
        self.run_native('''
free(g_mem);g_mem=calloc(1,0x1000000);ws_configure(".");assert(ws_patch_init());ws_set_resolution(1920,1080);
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->eax=0x1234;fragment_6c8786(c);
assert(c->esp==0x7ff4&&MR32(c->esp)==0x1234&&MR32(c->esp+4)==4096&&MR32(c->esp+8)==4096);
c->esp=0x8000;fragment_6c87b8(c);assert(c->esp==0x7ff4&&MR32(c->esp+4)==4096&&MR32(c->esp+8)==4096);
fragment_6c86b0(c);assert(c->eax==4096);fragment_6c86c0(c);assert(c->eax==4096);
c->esp=0x8000;MR32(0x982bdc)=0x6000;MR32(0x6000)=0x7000;MRF32(0x901abc)=4;
fragment_6e5507(c);assert(c->esp==0x7ff4&&MR32(c->esp)==0x6000&&MR32(c->esp+4)==175&&MRF32(c->esp+8)==8);
fragment_6de379(c);assert(!MR32(0x982ba8));
c->esp=0x8000;fragment_6e5173(c);assert(MR32(c->esp)==0);
fragment_6bffa1(c);assert(MR32(c->esp)==0x6102);fragment_6660ff(c);assert(MRF32(c->esp)==1.f/120);
''',self.asset_text('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini'),fragments)

    def test_supplied_shadow_getter_patches_both_select_second_match(self):
        image=self.runtime_image()
        import pefile
        module=pefile.PE(str(self.asset_path('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.asi')))
        # Both original calls pass index1 to the real match-array accessor.
        self.assertEqual(module.get_data(0xf8ca,2),b'\x6a\x01')
        self.assertEqual(module.get_data(0xf92b,2),b'\x6a\x01')
        import pefile as pe
        game=pe.PE(str(image));section=next(s for s in game.sections if s.Name.startswith(b'.text'))
        pattern=game.get_data(0x6c86b0-0x400000,6)
        import capstone
        decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
        self.assertEqual([(i.mnemonic,i.op_str) for i in decoder.disasm(pattern,0x6c86b0)],
                         [('mov','eax, 0x400'),('ret','')])
        matches=[0x400000+section.VirtualAddress+m.start() for m in re.finditer(re.escape(pattern),section.get_data())]
        self.assertEqual(matches,[0x4afefd,0x6c86b0,0x6c86c0])
        # The first write removes that match before the second fresh scan.
        memory=bytearray(game.get_memory_mapped_image())
        for dimension in (4096,4096):
            matches=[m.start() for m in re.finditer(re.escape(pattern),memory)]
            operand=matches[1]+1;memory[operand:operand+4]=dimension.to_bytes(4,'little')
        self.assertEqual(memory[0x6c86b1-0x400000:0x6c86b5-0x400000],(4096).to_bytes(4,'little'))
        self.assertEqual(memory[0x6c86c1-0x400000:0x6c86c5-0x400000],(4096).to_bytes(4,'little'))

    def test_shadow_width_scaling_matches_actual_inline_callbacks(self):
        path=self.asset_path('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.asi')
        from tools.lift import Lifter
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'32a087267fe2b08ec1213666893502dfccad014654324edf5d8cffc22a611353')
        lifter=Lifter(str(path));conversion,_=lifter.lift(0x100199df)
        # Execute the actual non-AVX, positive in-range conversion path.
        # The supplied reg-pack width fixtures cannot enter its large-value path.
        conversion=conversion[:conversion.index('L_100199f3:')]+'L_100199f3:__builtin_trap();}\n'
        fragments=conversion.replace('sub_100199df','sub_100199c0')
        for start in (0x10017440,0x10017470,0x100174a0):fragments+=lifter.lift(start)[0]
        self.run_native('''
free(g_mem);g_mem=calloc(1,0x11000000);ws_configure(".");assert(ws_patch_init());
CPU cpu={0},*c=&cpu;unsigned dimensions[][2]={{1920,1080},{1600,1200},{3440,1440}};
unsigned widths[]={640,1024,0x10400};unsigned sites[]={0x6e4668,0x6e46ac,0x6e47e4,0x6e482c};
for(unsigned d=0;d<3;d++)for(unsigned n=0;n<3;n++)for(unsigned kind=0;kind<4;kind++){
 ws_set_resolution(dimensions[d][0],dimensions[d][1]);MRF32(0x10057320)=((float)dimensions[d][1]/dimensions[d][0])/.85f;
 memset(c,0,sizeof *c);c->esp=0x8000;c->ebx=0x10000;c->eax=17;c->ecx=23;c->edx=29;c->zf=c->cf=1;
 MR32(c->ebx+0xc4)=widths[n];MR32(0x6010)=c->ebx;CPU initial=*c;
 PUSH32(0x6000);PUSH32(0x1234);
 if(kind==0)sub_10017440(c);else if(kind==3)sub_100174a0(c);else sub_10017470(c);
 uint32_t expected=MR32(0x6000+(kind==0?0x1c:kind==3?0x14:0x18));
 *c=initial;assert(ws_hook(c,sites[kind]));
 if(kind==0){assert(c->eax==expected);c->eax=initial.eax;}
 else if(kind==3){assert(c->edx==expected);c->edx=initial.edx;}
 else{assert(c->ecx==expected);c->ecx=initial.ecx;}
 assert(!memcmp(c,&initial,sizeof *c));
}
''','[MISC]\nShadowsRes=4096\n',fragments)

    def test_unsupported_or_malformed_patch_options_fail_explicitly(self):
        for ini in ('[MISC]\nSimRate=-3\n','[MISC]\nShadowsRes=9000\n','[MISC]\nShadowsRes=\n',
                    '[MISC]\nSimRate=1junk\n','[MISC]\nShadowsFix=.5\n',
                    '[NOSTrail]\nFixNOSTrailPosition=1\n','[NOSTrail]\nCustomNOSTrailLength=nan\n'):
            self.run_native('free(g_mem);g_mem=calloc(1,0x1000000);ws_configure(".");assert(!ws_patch_init());',ini)

    def test_historical_vendor_substitutions_are_scoped_to_selected_config(self):
        image=self.runtime_image()
        from tools.lift import Lifter
        lifter=Lifter(str(image));fixtures=[];offset=0
        while True:
            found=lifter.TDATA.find(bytes.fromhex('98d89300'),offset)
            if found<0:break
            for back in (1,2):
                instruction=next(lifter.md.disasm(lifter.TDATA[found-back:found+12],lifter.TVA+found-back))
                if instruction.mnemonic in ('mov','cmp') and '[0x93d898]' in instruction.op_str:break
            self.assertIn(instruction.mnemonic,('mov','cmp'))
            fixtures.append((instruction.address+instruction.size,instruction.mnemonic,instruction.op_str));offset=found+4
        self.assertEqual(len(fixtures),20)
        body='free(g_mem);g_mem=calloc(1,0x1000000);ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x1000;MR32(0x93d898)=0x10de;MR32(0x8f23f0)=0x3f99999a;\n'
        for site,mnemonic,operands in fixtures:
            if mnemonic=='mov':
                register=operands.split(',')[0];body+=f'c->{register}=17;assert(ws_hook(c,0x{site:x}));assert(c->{register}==0x3f99999a);\n'
            else:
                comparator=int(operands.split(',')[1].strip(),0)
                body+=f'{{CPU expected=*c;CPU *saved=c;c=&expected;uint32_t a=0x3f99999a,b={comparator},result=a-b;FLAGS_SUB(a,b,result,32);c=saved;assert(ws_hook(c,0x{site:x}));assert(!memcmp(c,&expected,sizeof *c));}}\n'
        body+='assert(MR32(0x93d898)==0x10de);\n'
        self.run_native(body,'[MISC]\nShadowsRes=4096\n')

    def test_simulation_steps_use_selected_display_rate_and_freeze_once(self):
        for rate,resolved in ((-1,120),(-2,240),(60,60),(144,144)):
            self.run_native('''
free(g_mem);g_mem=calloc(1,0x1000000);ws_configure(".");assert(ws_patch_init());
CPU cpu={0},*c=&cpu;c->esp=0x1000;c->top=4;c->st[4]=2;c->eax=123;c->cf=1;
CPU expected=*c;assert(ws_branch(c,0x6612ea)==1);assert(c->top==4&&c->st[4]==2*(double)(1.f/RATE));
c->st[4]=2;assert(!memcmp(c,&expected,sizeof *c));
assert(MRF32(0x903290)==1.f/RATE);refresh=60;
assert(ws_branch(c,0x65c78d)==1);assert(c->top==3&&c->st[3]==(double)(1.f/RATE));
assert(ws_branch(c,0x65c7d7)==1);assert(c->top==2&&c->st[2]==(double)(1.f/RATE));
assert(ws_hook(c,0x666104)&&MRF32(c->esp)==1.f/RATE);
'''.replace('RATE',str(resolved)),f'[MISC]\nSimRate={rate}\nShadowsFix=0\n')
        self.run_native('''
free(g_mem);g_mem=calloc(1,0x1000000);ws_configure(".");assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->esp=0x1000;CPU before=*c;
unsigned sites[]={0x6612ea,0x65c78d,0x65c7d7};for(unsigned i=0;i<3;i++)assert(!ws_branch(c,sites[i]));
MR32(c->esp)=123;MR32(0x903290)=456;ws_hook(c,0x666104);ws_hook(c,0x75aad8);
assert(!memcmp(c,&before,sizeof *c)&&MR32(c->esp)==123&&MR32(0x903290)==456);
''','[MISC]\nSimRate=0\nShadowsFix=0\n[NOSTrail]\nFixNOSTrailLength=0\n')

    def test_nos_delta_scaling_matches_actual_supplied_sse_cave(self):
        path=self.asset_path('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.asi')
        from tools.lift import Lifter
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'32a087267fe2b08ec1213666893502dfccad014654324edf5d8cffc22a611353')
        code,_=Lifter(str(path)).lift(0x10014540)
        code=re.sub(r'DISPATCH_TAIL\(c, (MR32\([^;]+)\);[^\n]*',r'c->eip=\1;return;',code)
        fragments='guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];\n'+code
        self.run_native('''
free(g_mem);g_mem=calloc(1,0x11000000);ws_configure(".");assert(ws_patch_init());
CPU cpu={0},*c=&cpu;c->esp=0x8000;c->edx=0x2000;c->esi=0x3000;c->eax=17;c->top=4;c->st[4]=1.25;
memset(c->xmm,0x5a,sizeof c->xmm);CPU initial=*c;
float first[]={4.5f,-1.f,10.f},second[]={1.f,3.f,-4.f};memcpy(g_mem+0x2000,first,sizeof first);memcpy(g_mem+0x3000,second,sizeof second);
MRF32(0x10056084)=2;MR32(0x10056090)=0x745040;sub_10014540(c);CPU expected=*c;float expected_delta[3];memcpy(expected_delta,g_mem+0x8030,sizeof expected_delta);
*c=initial;memset(g_mem+0x8030,0,sizeof expected_delta);assert(ws_branch(c,0x745038));expected.eip=c->eip;
assert(!memcmp(c,&expected,sizeof *c)&&!memcmp(expected_delta,g_mem+0x8030,sizeof expected_delta));
''','[MISC]\nSimRate=-1\nShadowsFix=0\n[NOSTrail]\nFixNOSTrailLength=1\nCustomNOSTrailLength=1\n',fragments)

    def test_selected_shadow_settings_apply_without_changing_legacy_mode(self):
        full=self.asset_text('out/installed/.nfsmw/full/scripts/NFSMostWanted.WidescreenFix.ini')
        standard=self.asset_text('out/installed/scripts/NFSMostWanted.WidescreenFix.ini')
        for ini,x,y in ((full,4096,4096),(standard,3094,2048)):
            self.run_native('''
free(g_mem);g_mem=calloc(1,0x1000000);assert(g_mem);ws_configure(".");assert(ws_patch_init());ws_set_resolution(1920,1080);
CPU cpu={0},*c=&cpu;c->esp=0x1000;c->eax=1024;CPU before=*c;
assert(ws_hook(c,0x6c86c5)&&c->eax==Y);c->eax=before.eax;assert(!memcmp(c,&before,sizeof *c));
assert(ws_hook(c,0x6c86b5)&&c->eax==X);c->eax=before.eax;
MR32(c->esp)=MR32(c->esp+4)=1024;assert(ws_hook(c,0x6c8790));assert(MR32(c->esp)==X&&MR32(c->esp+4)==Y);
assert(ws_hook(c,0x6c87c2));assert(MR32(c->esp)==X&&MR32(c->esp+4)==Y);
MR32(c->esp)=0x200;assert(ws_hook(c,0x6e5178)&&MR32(c->esp)==0);
MR32(c->esp)=0x4100;assert(ws_hook(c,0x6bffa6)&&MR32(c->esp)==0x6102);
assert(ws_branch(c,0x6de377)==1);MR32(0x982ba8)=0x3f800000;
assert(ws_hook(c,0x6de383)&&MR32(0x982ba8)==0&&MRF32(0x8a0e50)==60);
'''.replace('X',str(x)).replace('Y',str(y)),ini)
        self.run_native('''
assert(ws_patch_init());CPU cpu={0},*c=&cpu;c->eax=123;c->esp=0x1000;CPU before=*c;
assert(ws_hook(c,0x6c86c5)&&!memcmp(c,&before,sizeof *c));assert(!ws_branch(c,0x6de377));
''')

    def test_physical_resolution_is_independent_of_the_logical_mapping(self):
        self.run_native('''
unsigned width=17,height=19;
assert(!ws_get_resolution(&width,&height)&&width==17&&height==19);
ws_set_mapping(.75f);assert(!ws_get_resolution(&width,&height));
ws_set_resolution(1920,1080);assert(ws_get_resolution(&width,&height)&&width==1920&&height==1080);
ws_set_mapping(1);assert(ws_get_resolution(&width,&height)&&width==1920&&height==1080);
ws_set_resolution(0,720);assert(ws_get_resolution(&width,&height)&&width==1920&&height==1080);
ws_set_resolution(1600,1000);assert(ws_get_resolution(&width,0)&&width==1600);
assert(ws_get_resolution(0,&height)&&height==1000);assert(ws_get_resolution(0,0));
''')

    def test_hq_ini_accepts_original_double_slash_comments(self):
        self.run_native('''
ws_configure(".");ws_set_mapping(.75f);ws_set_resolution(1920,1080);
assert(fabsf(ws_ui_x()-.69f)<.00001f);
''', '[MAIN]\nFEScale = .92 // HQ frontend scale\n')

    def test_hud_uses_its_640x480_canvas_even_from_a_five_fourths_game_mode(self):
        self.run_native('''
ws_set_mapping(.703125f);ws_set_resolution(1920,1080);
assert(fabsf(ws_ui_x()-.75f)<.00001f);assert(ws_ui_y()==1);
ws_set_resolution(1080,1920);
assert(ws_ui_x()==1);assert(fabsf(ws_ui_y()-.421875f)<.00001f);
''')

    def test_graphics_corrections_keep_screen_effects_in_the_new_aspect(self):
        self.run_native('''
ws_set_resolution(1920,1080);CPU cpu={0},*c=&cpu;
c->st[0]=640;ws_hook(c,0x6c9c4b);assert(fabs(c->st[0]-853.33333)<.001);
c->st[0]=.0015625f;ws_hook(c,0x6d4c21);assert(fabs(c->st[0]-.001171875)<.000001);
c->st[0]=1.1f;ws_hook(c,0x6c9659);assert(fabs(c->st[0]-10)<.00001);
''')

    def test_hook_sites_match_supported_executable_instruction_boundaries(self):
        image=self.runtime_image()
        import capstone
        import pefile
        data=image.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),'80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c')
        pe=pefile.PE(data=data)
        expected={0x6cf4f6:'fstp',0x6cf56c:'fstp',0x6cf57e:'call',0x6cf5e2:'fld',
                  0x6e466c:'mov',0x6e47f0:'fmul',0x6e46b6:'fstp',0x6e4836:'fstp',
                  0x6d4811:'fadd',0x6d482f:'fadd',0x59a03f:'call',
                  0x6c9659:'fstp',0x6c9c4b:'fidiv',0x6d4c21:'mov',0x4c41f9:'mov',0x591460:'push'}
        expected.update({0x6c149f:'xor',0x6c14e1:'xor',0x6c15db:'xor',0x6c165b:'cmp',0x6c16db:'dec',0x6c16fd:'cmp',0x6c1a97:'push',0x6c1b6f:'jne',0x6c509a:'jne',0x6c50ea:'jne',0x6c5f08:'xor',0x6c5f52:'xor',0x6cfdb5:'xor',0x6cfdfa:'xor',0x6d2105:'cmp',0x6d5c39:'mov',0x6d5de1:'cmp',0x6df920:'cmp',0x6df9a3:'jne',0x6e6b6f:'push',0x6e75ac:'mov',0x6c86b5:'ret',0x6c86c5:'ret',0x6c8790:'push',0x6c87c2:'push',0x6e550d:'mov',0x6e5178:'jmp',0x6bffa6:'push',0x6de383:'jmp',0x6e4668:'fidiv',0x6e46ac:'mov',0x6e47e4:'fild',0x6e482c:'mov',0x666104:'call',0x75aad8:'mov'})
        expected.update({0x5696ce:'cmp',0x58d886:'pop',0x57cb85:'jne',0x56885d:'je',0x47d416:'mov',0x47dcbc:'call',0x7f2981:'mov',0x7f29b8:'lea',0x7f29ca:'mov',0x7f201d:'mov',0x7f21cf:'mov',0x5696f6:'mov',0x569717:'mov',0x5c53c0:'sub',0x7f2ae9:'mov',0x6282d3:'ret',0x5a3141:'push',0x5a3146:'push'})
        sites={int(s,16) for s in re.findall(r'HOOK_SITE\((0x[0-9a-fA-F]+)\)',Path('runtime/mw_widescreen.c').read_text())}
        self.assertEqual(sites,set(expected))
        md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
        for address,mnemonic in expected.items():
            instruction=next(md.disasm(pe.get_data(address-0x400000,16),address))
            self.assertEqual(instruction.mnemonic,mnemonic,hex(address))

    def test_ini_switches_and_scaling_are_applied_natively(self):
        self.run_native('''
ws_configure("."); ws_set_mapping(.75f); ws_set_resolution(1920,1080);
assert(fabsf(ws_ui_x()-.69f)<.00001f);
CPU cpu={0},*c=&cpu;c->esp=0x1000;c->ecx=1;
ws_hook(c,0x6cf4f6);c->st[0]=2;ws_hook(c,0x6cf56c);assert(c->st[0]==1.5);
c->st[0]=2;ws_hook(c,0x6cf5e2);assert(fabs(c->st[0]-2.43)<.00001);
c->st[0]=4;ws_hook(c,0x6d4811);assert(fabs(c->st[0]-.5625)<.00001);
c->st[0]=4;ws_hook(c,0x6d482f);assert(c->st[0]==1.);
''', '[MAIN]\nScaling = 0 ; original\nFEScale = .92\n[GRAPHICS]\nRainDropletsScale = .25\n')
        self.run_native('''
ws_configure(".");ws_set_mapping(.75f);ws_set_resolution(1920,1080);
assert(ws_ui_x()==1 && ws_ui_y()==1);
CPU cpu={0},*c=&cpu;c->ecx=1;c->st[0]=2;
ws_hook(c,0x6cf4f6);assert(c->st[0]==2);
ws_hook(c,0x6cf56c);assert(c->st[0]==2);
ws_hook(c,0x6cf57e);assert(c->st[0]==2);
ws_hook(c,0x6cf5e2);assert(c->st[0]==2);
''', '[MAIN]\nFixHUD = 0\nFixFOV = 0\n')

    def test_high_spec_audio_preserves_full_renderer_and_explicit_rate_overrides(self):
        for enabled in (0,1):
            self.run_native('''
free(g_mem);g_mem=calloc(1,0x1000000);assert(g_mem);ws_configure(".");
assert(ws_high_spec_audio()==ENABLED);
CPU cpu={0},*c=&cpu;c->eax=17;c->esp=0x1000;c->cf=c->zf=1;CPU before=*c;
unsigned rates[]={22050,44100,48000,96000};
for(unsigned i=0;i<4;i++){
 MR32(0x8ee650)=rates[i];assert(ws_hook(c,0x4c41f9));
 assert(MR32(0x8ee650)==(i==0&&ENABLED?44100:rates[i]));
 assert(!memcmp(c,&before,sizeof *c));
}
'''.replace('ENABLED',str(enabled)),f'[MISC]\nForceHighSpecAudio = {enabled}\n')

    def test_shadow_cameras_use_the_same_horizontal_projection(self):
        self.run_native('''
ws_set_resolution(1920,1080);CPU cpu={0},*c=&cpu;
c->st[0]=2;ws_hook(c,0x6e466c);assert(c->st[0]==1);
c->st[0]=2;ws_hook(c,0x6e47f0);assert(c->st[0]==1);
c->st[0]=2;ws_hook(c,0x6e46b6);assert(fabs(c->st[0]-1.432)<.001);
c->st[0]=2;ws_hook(c,0x6e4836);assert(fabs(c->st[0]-1.432)<.001);
''')

    def test_projection_hooks_separate_world_mirror_and_reflection_views(self):
        self.run_native('''
ws_set_mapping(.75f); ws_set_resolution(1920,1080);
CPU cpu={0},*c=&cpu;c->esp=0x1000;
c->ecx=1; assert(ws_hook(c,0x6cf4f6)); assert(c->st[0]==1.);
c->st[0]=2.; assert(ws_hook(c,0x6cf56c)); assert(fabs(c->st[0]-1.432)<.001);
c->st[0]=.5; ws_hook(c,0x6cf57e); assert(fabs(c->st[0]-.43434)<.00001);
c->st[0]=2.; ws_hook(c,0x6cf5e2); assert(fabs(c->st[0]-2.42)<.00001);
c->ecx=3; ws_hook(c,0x6cf4f6); assert(fabs(c->st[0]-.4)<.00001);
c->st[0]=2.; ws_hook(c,0x6cf56c); assert(c->st[0]==2.);
c->ecx=11; ws_hook(c,0x6cf4f6); assert(c->st[0]==1.);
c->st[0]=.5; ws_hook(c,0x6cf57e); assert(c->st[0]==.5);
c->st[0]=2.; ws_hook(c,0x6cf5e2); assert(c->st[0]==2.);
c->ecx=4; ws_hook(c,0x6cf4f6); c->st[0]=2.; ws_hook(c,0x6cf56c);
assert(fabs(c->st[0]-1.432)<.001); assert(!ws_hook(c,0x123456));
''')

    def test_movie_fits_anamorphic_and_square_pixel_frames_without_skipping(self):
        self.run_native('''
ws_set_mapping(.75f); ws_set_resolution(1920,1080);
CPU cpu={0},*c=&cpu;c->esp=0x1000;c->ebx=0x2000;
MRF32(c->ebx+0x30)=640;MRF32(c->ebx+0x44)=480;MR32(c->esp+0x48)=0x3000;
MR16(0x3044)=1024;MR16(0x3046)=512;
MRF32(c->esp+20)=0;MRF32(c->esp+24)=0;MRF32(c->esp+28)=1;MRF32(c->esp+32)=1;
assert(ws_hook(c,0x59a03f));
assert(fabsf(MRF32(c->esp)+2.f/3.f)<.00001f);
assert(fabsf(MRF32(c->esp+4)+.5f)<.00001f);
assert(fabsf(MRF32(c->esp+24)-.125f)<.00001f);
assert(fabsf(MRF32(c->esp+32)-.875f)<.00001f); assert(clears==1);
MR16(0x3044)=1920;MR16(0x3046)=1080;
MRF32(c->esp+24)=0;MRF32(c->esp+32)=1;ws_hook(c,0x59a03f);
assert(MRF32(c->esp+24)==0 && MRF32(c->esp+32)==1);assert(clears==2);
MRF32(c->ebx+0x30)=320;MRF32(c->ebx+0x44)=240;
ws_hook(c,0x59a03f);assert(clears==2);
''')

    def test_x360_movie_wrapper_preserves_the_single_letterbox_crop(self):
        module=self.asset_path('out/hq-extract/normalized/LOGIC/41/X360Stuff.asi')
        import pefile
        from tools.lift import Lifter
        self.assertEqual(hashlib.sha256(module.read_bytes()).hexdigest(),
                         '0073249a7642a3c1d8bd196c5795cc22da8eb8218349762301ba66b686c00fe8')
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'x360.dll'
            pe=pefile.PE(str(module));pe.relocate_image(0x01000000)
            pe.OPTIONAL_HEADER.ImageBase=0x01000000;pe.write(str(image))
            wrapper,_=Lifter(str(image)).lift(0x010098c0)
        fragments=r'''
guest_fn_t g_dtab[DISPATCH_TEXT_SIZE];
static unsigned forwarded[12],polygons;
void dispatch_indirect(CPU *c,uint32_t target){
 assert(target==0x591460);CPU before=*c;
 ws_hook(c,0x591460);assert(!memcmp(c,&before,sizeof *c));
 for(unsigned i=0;i<12;i++)forwarded[i]=MR32(c->esp+4+i*4);
 polygons++;POP32(c->eip);c->esp+=48;c->eax=0x5000;
}
'''+wrapper
        self.run_native(r'''
free(g_mem);g_mem=calloc(1,0x1100000);assert(g_mem);
ws_configure(".");ws_set_resolution(1920,1080);MRF32(0x0102b564)=.92f;
CPU cpu={0},*c=&cpu;
for(unsigned movie=0;movie<2;movie++)for(unsigned flip=0;flip<2;flip++){
 memset(c,0,sizeof *c);c->esp=0x8000;c->ebp=0x9000;c->ebx=c->ecx=0x2000;c->edx=123;
 c->top=4;c->st[4]=1.25;c->cf=1;c->fcw=0x027f;
 MRF32(0x2030)=640;MRF32(0x2044)=480;MR32(0x8048)=0x3000;
 MR16(0x3044)=movie?2048:1024;MR16(0x3046)=movie?1024:512;
 MRF32(0x8010)=.25f;MRF32(0x8014)=0;MRF32(0x8018)=flip?1:0;
 MRF32(0x801c)=1;MRF32(0x8020)=flip?0:1;
 MR32(0x8024)=0x4000;MR32(0x8028)=17;MR32(0x802c)=35;
 assert(ws_hook(c,0x59a03f));
 assert(fabsf(MRF32(0x8000)+2.f/3.f)<.00001f&&MRF32(0x8004)==-.5f);
 assert(fabsf(MRF32(0x8018)-(flip?.875f:.125f))<.00001f);
 unsigned fitted[12];memcpy(fitted,g_mem+0x8000,sizeof fitted);
 PUSH32(0x59a044);sub_010098c0(c);
 assert(polygons==movie*2+flip+1&&c->esp==0x8030&&c->eip==0x59a044&&c->eax==0x5000);
 assert(c->ebp==0x9000&&c->top==4&&c->st[4]==1.25);
 assert(!memcmp(forwarded,fitted,sizeof fitted));
 assert(MRF32(0x0102b564)==.92f);
}
assert(clears==4);
for(unsigned control=0;control<3;control++){
 memset(c,0,sizeof *c);c->esp=0x8000;c->ebp=0x9000;c->eax=123;c->cf=c->zf=1;
 MR32(c->esp)=control==0?0x123456:0x0100992c;
 MR32(c->ebp+4)=control==1?0x654321:0x59a044;
 MR8(0x0102b560)=control==2;
 unsigned before_args[12];for(unsigned i=0;i<12;i++)before_args[i]=MR32(c->esp+4+i*4)=0xaabb0000+i;
 CPU before=*c;assert(ws_hook(c,0x591460));
 assert(!memcmp(c,&before,sizeof *c)&&!memcmp(before_args,g_mem+c->esp+4,sizeof before_args));
}
''', '[MAIN]\nFMVWidescreenMode=0\n',fragments)

    def run_native(self, body, ini=None, fragments='', keyboard=False, asset=True, gamepad=False):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'test.c'
            if ini is not None:
                scripts=Path(tmp)/'scripts';scripts.mkdir()
                (scripts/'NFSMostWanted.WidescreenFix.ini').write_text(ini)
                if asset and re.search(r'ImproveGamepadSupport\s*=\s*[12]',ini):
                    # The stubbed guest loader never parses the resource contents.
                    (scripts/'NFSMostWanted.WidescreenFix.tpk').write_bytes(b'test resource fixture')
            source.write_text('''#include "widescreen.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
uint8_t *g_mem; int clears;
static unsigned fe_calls,fe_allocations,fe_absent,dz_calls,tpk_loads;static uint32_t heap_next=0x7000;
static guest_fn_t visitor_callback,visitor_engine,logo_engine;
static unsigned key_calls,message_calls;
void kbd_set_key(int source,unsigned key,int down){assert(source==3&&key==0x10&&down==(key_calls%2==0));key_calls++;}
void kbd_post(uint32_t message,uint32_t wp,uint32_t lp){assert(wp==(message==0x102?'q':0x51));assert(message==0x100||message==0x101||message==0x102);assert(lp==(message==0x101?0xc0100001u:0x00100001u));message_calls++;}
void dispatch_patch(uint32_t address,guest_fn_t fn){assert(address==0xc1000000u);visitor_callback=fn;}static float selected_left,selected_right;
void gamepad_set_stick_deadzones(float left,float right){dz_calls++;selected_left=left;selected_right=right;}
uint32_t gheap_alloc(int heap,uint32_t size,int zero){assert(heap==1&&size&&size<256);uint32_t p=heap_next;heap_next+=(size+15)&~15u;if(zero)memset(g_mem+p,0,size);if(size==8)fe_allocations++;return p;}
uint32_t call_guest(CPU*c,uint32_t function,int count,const uint32_t*args){
 fe_calls++;uint32_t result=0;
 if(function==0x65fd30){assert(count==5&&!strcmp((char*)g_mem+args[0],"scripts\\\\NFSMostWanted.WidescreenFix.tpk"));tpk_loads++;result=0x19000;}
 else if(function==0x6616f0){assert(count==2&&c->ecx==0x19000&&!args[0]&&!args[1]);}
 else if(function==0x6626b0){assert(count==0);}
 else if(function==0x514cc0){assert(count==1&&logo_engine&&args[0]==0x60000);PUSH32(args[0]);PUSH32(0x87654321);logo_engine(c);assert(c->eip==0x87654321);result=c->eax;}
 else if(function==0x5b1560){assert(count==1&&visitor_engine);PUSH32(args[0]);PUSH32(0x87654321);visitor_engine(c);assert(c->eip==0x87654321);result=c->eax;}
 else if(function==0x516c90){assert(count==3&&args[1]==0x2000);}
 else if(function==0x524850){assert(count==2&&args[0]==0x2000);result=fe_absent?0:args[1]==0x1603009e?0x3000:0x4000;}
 else if(function==0x524ee0){assert(count==3);MR32(args[1])=MR32(args[0]);MR32(args[2])=MR32(args[0]+4);}
 else{assert(function==0x525050&&count==3);MR32(args[0])=args[1];MR32(args[0]+4)=args[2];}
 memset(c,0xa5,sizeof *c);return result;
}
static unsigned postfx_calls,postfx_gamma,postfx_border;
void com_widescreen_postfx(unsigned gamma,unsigned border){postfx_calls++;postfx_gamma=gamma;postfx_border=border;}
static int refresh=120;int metal_display_hz(void){return refresh;}
int ws_patch_init(void),ws_branch(CPU*,uint32_t);
void com_clear_movie_borders(void){clears++;}
''' + fragments + '''
int main(void){g_mem=calloc(1,0x1000000);
''' + body + '\nfree(g_mem);}\n')
            if keyboard:
                fixture=source.read_text()
                fixture=re.sub(r'^void kbd_set_key[^\n]*\n','',fixture,flags=re.M)
                fixture=re.sub(r'^void kbd_post[^\n]*\n','',fixture,flags=re.M)
                source.write_text(fixture)
            if gamepad:
                fixture=re.sub(r'^void gamepad_set_stick_deadzones[^\n]*\n','',source.read_text(),flags=re.M)
                source.write_text(fixture)
            result=subprocess.run(['clang','-O1',*(['-fobjc-arc'] if gamepad else []),'-Iruntime',str(source),'runtime/mw_widescreen.c',*(['runtime/keyboard.c'] if keyboard else []),*(['runtime/gamepad.m','-framework','Foundation','-framework','GameController'] if gamepad else []),'-lm','-o',str(Path(tmp)/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(Path(tmp)/'test')],capture_output=True,text=True,cwd=tmp)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_hud_keeps_circles_round_on_wide_and_portrait_screens(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.c'
            source.write_text('''#include "widescreen.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem; uint32_t g_watch_addr,g_watch_val; uint64_t g_mw_frame;
int metal_display_hz(void){return 120;}
void com_widescreen_postfx(unsigned gamma,unsigned border){(void)gamma;(void)border;}
void dispatch_patch(uint32_t address,guest_fn_t fn){(void)address;(void)fn;}
void kbd_set_key(int a,unsigned b,int d){(void)a;(void)b;(void)d;}
void kbd_post(uint32_t a,uint32_t b,uint32_t d){(void)a;(void)b;(void)d;}
uint32_t gheap_alloc(int heap,uint32_t size,int zero){(void)heap;(void)size;(void)zero;return 0;}
uint32_t call_guest(CPU*c,uint32_t fn,int n,const uint32_t*a){(void)c;(void)fn;(void)n;(void)a;return 0;}
void gamepad_set_stick_deadzones(float left,float right){(void)left;(void)right;}
void com_clear_movie_borders(void){}
int main(void){
ws_set_mapping(.75f); assert(fabsf(ws_ui_x()-.75f)<.00001f); assert(ws_ui_y()==1.f);
ws_set_mapping(2.f); assert(ws_ui_x()==1.f); assert(fabsf(ws_ui_y()-.5f)<.00001f);
ws_set_mapping(NAN); assert(ws_ui_x()==1.f && ws_ui_y()==1.f);
assert(ws_persp_x()==1.f && ws_persp_y()==1.f);
}
''')
            implementation = 'runtime/mw_widescreen.c' if Path('runtime/mw_widescreen.c').exists() else 'runtime/mw_platform.c'
            subprocess.run(['clang', '-O1', '-Iruntime', str(source), implementation, '-lm', '-o', str(Path(tmp)/'test')], check=True, capture_output=True)
            result=subprocess.run([str(Path(tmp)/'test')], capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
