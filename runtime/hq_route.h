#ifndef HQ_ROUTE_H
#define HQ_ROUTE_H
#include <stdint.h>
typedef struct { uint32_t address, length; } HQRouteRange;
int hq_route_match(const HQRouteRange *ranges, unsigned count, const uint8_t *signature);
#endif
