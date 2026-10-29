#ifndef HQ_NATIVE_H
#define HQ_NATIVE_H
#include "cpu.h"
typedef struct {uint32_t guest;void(*function)(CPU*);const char *name;} HQNativeEntry;
extern const HQNativeEntry g_hq_native[];
extern const unsigned g_hq_native_count;
void hq_native_resolve(const void *pc,uintptr_t *best,uint32_t *guest,const char **name);
#endif
