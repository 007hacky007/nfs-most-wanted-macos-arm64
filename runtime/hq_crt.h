#ifndef HQ_CRT_H
#define HQ_CRT_H
#include "cpu.h"
int hq_crt_dll(const char *dll);
int hq_crt_call(CPU *c, const char *name, uint32_t *result);
void hq_crt_thread_detach(void);
#endif
