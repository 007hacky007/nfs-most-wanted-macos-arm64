/* tools/texpacks.py NTXP v1 packs. Immutable metadata, thread-safe payload reads. */
#ifndef TEXPACK_H
#define TEXPACK_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t crc, adler;
    uint16_t ow, oh;
    uint32_t ofmt;
    uint16_t w, h;
    uint32_t fmt, levels, off, size, name;
} TexpackEntry;
typedef struct {
    int fd;
    unsigned count, shape_count;
    TexpackEntry *entries;
    uint64_t *shapes;
    char *names;
    uint32_t names_at;
} Texpack;

int texpack_open(Texpack *p, const char *path, char *err, size_t err_size);
void texpack_close(Texpack *p);
int texpack_may_match(const Texpack *p, unsigned w, unsigned h, unsigned fmt);
int texpack_find(const Texpack *p, const uint8_t *data, size_t size, unsigned w, unsigned h, unsigned fmt);
int texpack_read(const Texpack *p, unsigned index, void *data, size_t size);
const char *texpack_name(const Texpack *p, unsigned index);
#endif
