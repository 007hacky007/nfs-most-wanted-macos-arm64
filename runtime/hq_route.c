#include "cpu.h"
#include "hq_route.h"
int hq_route_match(const HQRouteRange *ranges, unsigned count, const uint8_t *signature){
    for (unsigned i = 0; i < count; i++){
        if (memcmp(g_mem + ranges[i].address, signature, ranges[i].length)) return 0;
        signature += ranges[i].length;
    }
    return 1;
}
