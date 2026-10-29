/* Native core limits for the HQ pack's Unlimiter 3.3.0.1338 behavior.
 * Independently implemented against the supported executable's instructions.
 * Behavior reference: https://github.com/nlgxzef/NFSMWUnlimiter/tree/c07b7124bcf11aacceced9d7fa7670d82199c4b6
 * Hooks run immediately before the indicated guest instruction, after its cmp.
 * shortcut: covers core limits only; customization and skin hooks need separate ports.
 */
#include "cpu.h"
#define HOOK_SITE(a) a

static int enabled;
static uint32_t car_count = 84;

void mw_unlimiter_init(int active){
    enabled = active != 0;
    car_count = 84;
}

static void compare(CPU *c, uint32_t a, uint32_t b){
    uint32_t result = a - b;
    FLAGS_SUB_M(a, b, result, 32, 0x3fu);
}

int mw_unlimiter_hook(CPU *c, uint32_t ip){
    switch (ip){
    case HOOK_SITE(0x756AAD): {
        if (!enabled) return 1;
        if (c->esi < 12) return 1;
        uint32_t size = MR32(c->esi - 12);
        if (size > 8 && (size - 8) % 208 == 0 && (size - 8) / 208 <= 4096)
            car_count = (size - 8) / 208;
        return 1;
    }
    case HOOK_SITE(0x6690BE):
    case HOOK_SITE(0x73995E):
    case HOOK_SITE(0x7515FE):
        if (enabled) compare(c, c->eax, car_count); return 1;
    case HOOK_SITE(0x7398A9):
    case HOOK_SITE(0x759916):
        if (enabled) compare(c, c->ecx, car_count); return 1;
    case HOOK_SITE(0x75E6F7):
    case HOOK_SITE(0x75E7B7):
        if (enabled) compare(c, c->esi, car_count); return 1;
    case HOOK_SITE(0x739904):
        if (enabled) compare(c, c->esi, car_count * 208); return 1;
    case HOOK_SITE(0x7B3881):
        if (enabled) compare(c, c->ebp, car_count * 208); return 1;
    case HOOK_SITE(0x73990D):
        if (enabled) c->eax = 1; return 1;
    case HOOK_SITE(0x75C710):
        if (enabled && !c->eax){
            c->edx = 1;
            MR32(c->ebx) = 1;
            c->zf = 0; /* Skip the original failed-model assertion call. */
        }
        return 1;
    case HOOK_SITE(0x439B7A):
    case HOOK_SITE(0x410963):
        if (enabled) compare(c, c->esi, 20); return 1;
    case HOOK_SITE(0x4265C3):
        if (enabled) compare(c, c->edi, 20); return 1;
    case HOOK_SITE(0x42625A):
        if (enabled) c->ecx = 20;
        if (enabled) compare(c, c->eax, 20); return 1;
    case HOOK_SITE(0x74251E):
        if (enabled && c->zf) MR8(c->esp + 23) = 1;
        return 1;
    default:
        return 0;
    }
}
