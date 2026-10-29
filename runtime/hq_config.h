#ifndef HQ_CONFIG_H
#define HQ_CONFIG_H
#include <stdint.h>
typedef struct {const char *section,*key;unsigned offset;char type;unsigned length;} HQField;
#define HQ_XENON_CONFIG_BASE 0x02413000u
#define HQ_XENON_CONFIG_SIZE 0x889u
int hq_config_xenon_load(const char *,uint8_t [HQ_XENON_CONFIG_SIZE],uint64_t *);
#define HQ_CONFIG_SIZE 0x254u
int hq_config_load(const char *,uint8_t [HQ_CONFIG_SIZE]);
#endif
