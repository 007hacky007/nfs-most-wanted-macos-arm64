#include "vsemu.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void check(unsigned version, unsigned reg, int initialized) {
    uint32_t code[] = {
        0xffff0000u | version,
        0x0200001fu, 0x80000000u, 0xb00f0000u | reg,
        0x02000001u, 0x800f0800u, 0xb0e40000u | reg,
        0x0000ffffu
    };
    VSProg *p = vs_compile(code, sizeof code / sizeof *code);
    assert(p && !vs_unknown(p));
    char msl[32768], expected[64];
    assert(ps_to_msl(p, 0, msl, sizeof msl));
    assert(strstr(msl, "saturate(i.col0)") && strstr(msl, "saturate(i.col1)"));
    snprintf(expected, sizeof expected, "t[%u] = i.uv%u;", reg, reg);
    assert((strstr(msl, expected) != NULL) == initialized);
    vs_free(p);
}

int main(void) {
    for (unsigned reg = 0; reg < 4; reg++) check(0x0200, reg, 1);
    check(0x0104, 0, 0);
    puts("PASS: ps_2_0 declared texture coordinates, ps_1_4 unchanged");
}
