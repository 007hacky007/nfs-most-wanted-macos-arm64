#ifndef HQ_TLS_H
#define HQ_TLS_H
#include <stdint.h>
struct CPU;
#define HQ_STATIC_TLS_SLOT 128u
#define HQ_STATIC_TLS_COUNT 5u
int hq_tls_enable_slot(uint32_t data,uint32_t size,uint32_t index,uint32_t slot);
int hq_tls_enable(uint32_t data,uint32_t size,uint32_t index);
int hq_tls_attach(struct CPU *);
void hq_tls_detach(struct CPU *);
#endif
