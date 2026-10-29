#ifndef HQ_CAPTURE_H
#define HQ_CAPTURE_H
#include "cpu.h"
void hq_capture_prepare(void);
void hq_capture_fault(const CPU *c,uint32_t address,uint32_t guest,const char *name);
void hq_capture(CPU *c,const char *reason,uint32_t address);
const char *hq_capture_path(const char *name);
#endif
