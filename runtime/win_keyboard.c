/* Windows virtual keys for the port's scan-code keyboard. */
#include "cpu.h"
#include "kbd.h"
#include <ctype.h>
void mem_commit(uint32_t,uint32_t);

static unsigned scan_for(unsigned vk){
    static const unsigned letters[]={0x1e,0x30,0x2e,0x20,0x12,0x21,0x22,0x23,0x17,0x24,0x25,0x26,0x32,
        0x31,0x18,0x19,0x10,0x13,0x1f,0x14,0x16,0x2f,0x11,0x2d,0x15,0x2c};
    if(vk>='A'&&vk<='Z')return letters[vk-'A'];
    if(vk>='1'&&vk<='9')return vk-'1'+2;
    if(vk=='0')return 0x0b;
    switch(vk){
    case 8:return 0x0e;case 9:return 0x0f;case 13:return 0x1c;case 16:case 0xa0:return 0x2a;
    case 0xa1:return 0x36;case 17:case 0xa2:return 0x1d;case 0xa3:return 0x9d;
    case 18:case 0xa4:return 0x38;case 0xa5:return 0xb8;case 20:return 0x3a;
    case 27:return 1;case 32:return 0x39;case 33:return 0xc9;case 34:return 0xd1;
    case 35:return 0xcf;case 36:return 0xc7;case 37:return 0xcb;case 38:return 0xc8;
    case 39:return 0xcd;case 40:return 0xd0;case 45:return 0xd2;case 46:return 0xd3;
    case 0xba:return 0x27;case 0xbb:return 0x0d;case 0xbc:return 0x33;case 0xbd:return 0x0c;
    case 0xbe:return 0x34;case 0xbf:return 0x35;case 0xc0:return 0x29;
    case 0xdb:return 0x1a;case 0xdc:return 0x2b;case 0xdd:return 0x1b;case 0xde:return 0x28;
    default:return vk>=0x70&&vk<=0x79?vk-0x70+0x3b:0;
    }
}

static unsigned vk_for(unsigned scan){
    if((scan&0xff00)==0xe000)scan=(scan&255)|128;
    for(unsigned vk=1;vk<256;vk++)if(scan_for(vk)==scan)return vk;
    return 0;
}

static unsigned character(unsigned vk,int shifted,int caps){
    if(vk>='A'&&vk<='Z')return shifted!=caps?vk:vk+32;
    if(vk>='0'&&vk<='9')return shifted?(unsigned)")!@#$%^&*("[vk-'0']:vk;
    if(vk==13||vk==9||vk==8||vk==27||vk==32)return vk;
    static const unsigned codes[]={0xba,0xbb,0xbc,0xbd,0xbe,0xbf,0xc0,0xdb,0xdc,0xdd,0xde};
    for(unsigned i=0;i<sizeof codes/sizeof *codes;i++)if(vk==codes[i])return (unsigned)(shifted?":+<_>?~{|}\"":";=,-./`[\\]'" )[i];
    return 0;
}

static int pressed(unsigned vk){
    unsigned scan=scan_for(vk);
    if(scan&&kbd_key_down(scan))return 1;
    return (vk==16&&kbd_key_down(0x36))||(vk==17&&kbd_key_down(0x9d))||(vk==18&&kbd_key_down(0xb8));
}

int win_keyboard_call(CPU *c,const char *name,uint32_t *result){
    uint32_t a=MR32(c->esp),b=MR32(c->esp+4);*result=0;
    if(!strcmp(name,"GetKeyboardLayout"))*result=0x04090409u;
    else if(!strcmp(name,"MapVirtualKeyA")||!strcmp(name,"MapVirtualKeyExA")){
        if(b==0||b==4){unsigned scan=scan_for(a);*result=b==4&&scan&128?(scan&127)|0xe000:scan&127;}
        else if(b==1||b==3)*result=vk_for(a);
        else if(b==2){unsigned ch=character(a,0,0);*result=(ch>='a'&&ch<='z')?ch-32:ch;}
    }
    else if(!strcmp(name,"GetKeyState")||!strcmp(name,"GetAsyncKeyState")){
        *result=pressed(a)?0x8000:0;
    }
    else if(!strcmp(name,"GetKeyboardState")){
        if(a){mem_commit(a,256);for(unsigned vk=0;vk<256;vk++)MR8(a+vk)=pressed(vk)?0x80:0;*result=1;}
    }
    else if(!strcmp(name,"ToUnicode")){
        uint32_t state=MR32(c->esp+8),out=MR32(c->esp+12),count=MR32(c->esp+16);
        int shifted=state?!!(MR8(state+16)&0x80):0,caps=state?!!(MR8(state+20)&1):0;
        unsigned ch=character(a,shifted,caps);
        if(ch&&out&&count){mem_commit(out,2);MR16(out)=(uint16_t)ch;*result=1;}
    }
    else return 0;
    return 1;
}
