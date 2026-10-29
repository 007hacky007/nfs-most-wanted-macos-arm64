/* Logical asset dimensions used by HD Content Support 2.0.
 * Behavior reference: AeroWidescreen/NFSHDContentSupport, SOURCE/NFSMW.
 * Hooks follow the original dimension loads so texture metadata stays intact.
 */
#include "cpu.h"
#define HOOK_SITE(a) a

static int active;

void mw_hdscaling_init(int enabled){ active = enabled != 0; }

static unsigned font_width(uint32_t texture){
    switch (MR32(texture + 0x24)){
    case 0xa87927be: /* FONT_ARIAL */
    case 0xab6215c1: /* FONT_ARIAL12 */
    case 0x545570c6: return 256; /* FONT_MW_BODY */
    case 0xe0463afa: return 512; /* FONT_MW_TITLE */
    case 0xc7bd87ce: /* FONT_MW_CUSTOM_NUMBERS */
    case 0x01424892: return 128; /* TAC_NUMBERS */
    default: return 0;
    }
}

int mw_hdscaling_hook(CPU *c, uint32_t ip){
    unsigned width;
    switch (ip){
    case HOOK_SITE(0x00585d7f):
        if (active && (width = font_width(MR32(c->ecx + 8)))){
            MR32(c->esp + 0x24) = width;
            c->esi = width == 128 ? 64 : width;
        }
        return 1;
    case HOOK_SITE(0x006d1502):
        if (active && (width = font_width(c->ecx))){
            MR32(c->esp + 0x18) = c->edx = width;
            c->eax = width == 128 ? 64 : width;
        }
        return 1;
    case HOOK_SITE(0x00570460):
    case HOOK_SITE(0x0057049a):
        if (active) c->ecx = 16;
        return 1;
    case HOOK_SITE(0x00570485):
    case HOOK_SITE(0x005704c3):
        if (active) c->eax = 16;
        return 1;
    case HOOK_SITE(0x00599f16):
        if (active){ c->eax = 1024; c->edx = 512; }
        return 1;
    default: return 0;
    }
}
