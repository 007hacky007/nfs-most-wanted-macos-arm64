#ifndef HQ_PREPARE_H
#define HQ_PREPARE_H
#include "cpu.h"

int hq_prepare_run(CPU *c);
void hq_prepare_import(CPU *c,const char *name);
void hq_prepare_checkpoint(CPU *c,unsigned point);

#endif
