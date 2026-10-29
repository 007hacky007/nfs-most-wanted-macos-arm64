#ifndef HQ_PLUGIN_H
#define HQ_PLUGIN_H
#include "cpu.h"
int hq_plugin_enabled(void);
void hq_plugin_init_unlimiter(int full);
void hq_plugin_checkpoint(CPU *c,unsigned point);
int hq_plugin_mapped(CPU *c);
int hq_plugin_module_mapped(CPU *c,uint32_t base);
void hq_plugin_thread(CPU *c);
int hq_plugin_prepare(CPU *c, const char *config_path);
int hq_plugin_prepare_addons(CPU *c);
int hq_plugin_override(CPU *c, uint32_t address);
void hq_plugin_route_error(CPU *c, uint32_t address);
uint32_t hq_plugin_data_import(const char *name);
#endif
