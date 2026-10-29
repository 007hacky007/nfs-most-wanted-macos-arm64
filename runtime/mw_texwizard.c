/* Native hash substitution and resource registration for the supplied HQ pack.
 * Behavior reference: https://github.com/R-033/texwizard (GPL-3.0).
 * Independently implemented against the supported game's calling conventions.
 * shortcut: supports TEX/ROCKPORT360 only; add pack discovery if another pack is needed.
 */
#include "cpu.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#define HOOK_SITE(a) a
#define MAP_MAX 4096
#define JSON_MAX 131072

int fileio_resolve_game(const char *, char *, size_t);
uint32_t gheap_alloc(int, uint32_t, int);
uint32_t call_guest(CPU *, uint32_t, int, const uint32_t *);

static struct { uint32_t key, value; } mappings[MAP_MAX];
static unsigned map_count;
static int active;
static uint32_t resource;
static uint64_t pack_bytes, replacements, confirmed;
static const char pack_name[] = "TEX\\ROCKPORT360\\textures.bin";

static const char *space(const char *p){
    while (p && *p){
        if (isspace((unsigned char)*p)){ p++; continue; }
        if (p[0] == '/' && p[1] == '/'){
            while (*p && *p != '\n') p++;
            continue;
        }
        if (p[0] == '/' && p[1] == '*'){
            p = strstr(p + 2, "*/");
            if (!p) return NULL;
            p += 2; continue;
        }
        break;
    }
    return p;
}

static int take(const char **p, char token){
    *p = space(*p);
    if (!*p || **p != token) return 0;
    (*p)++; return 1;
}

static int text(const char **p, char out[128]){
    if (!take(p, '"')) return 0;
    unsigned n = 0;
    while (**p && **p != '"'){
        unsigned char c = (unsigned char)*(*p)++;
        if (c == '\\'){
            c = (unsigned char)*(*p)++;
            if (c != '"' && c != '\\' && c != '/') return 0;
        }
        if (c < 32 || c > 126 || n == 127) return 0;
        out[n++] = (char)c;
    }
    out[n] = 0;
    return take(p, '"');
}

static int name_hash(const char *s, uint32_t *hash){
    if (s[0] == '0' && s[1] == 'x'){
        char *end;
        errno = 0;
        unsigned long value = strtoul(s + 2, &end, 16);
        if (errno || end == s + 2 || *end || value > UINT32_MAX) return 0;
        *hash = (uint32_t)value;
    } else {
        *hash = UINT32_MAX;
        for (; *s; s++) *hash = *hash * 33 + (unsigned char)*s;
    }
    return 1;
}

static int sort_mapping(const void *a, const void *b){
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return (x > y) - (x < y);
}

static int parse(const char *p){
    char key[128], value[128];
    if (!take(&p, '{') || !text(&p, key) || strcmp(key, "textures")
            || !take(&p, ':') || !take(&p, '[')) return 0;
    for (;;){
        p = space(p);
        if (!p) return 0;
        if (*p == ']') break;
        uint32_t from, to;
        if (!take(&p, '[') || !text(&p, key) || !take(&p, ',')
                || !text(&p, value) || !take(&p, ']')
                || !name_hash(key, &from) || !name_hash(value, &to)) return 0;
        unsigned i;
        for (i = 0; i < map_count && mappings[i].key != from; i++) {}
        if (i == MAP_MAX) return 0;
        if (i == map_count) map_count++;
        mappings[i].key = from; mappings[i].value = to;
        p = space(p);
        if (!p) return 0;
        if (*p != ',') break;
        p++;
    }
    if (!take(&p, ']') || !take(&p, '}')) return 0;
    p = space(p);
    if (!p || *p || !map_count) return 0;
    qsort(mappings, map_count, sizeof mappings[0], sort_mapping);
    return 1;
}

/* Call after fileio_set_root. Returns the mapping count, 1 when disabled, 0 on error. */
int mw_texwizard_init(int requested){
    active = 0; map_count = 0; resource = 0; pack_bytes = replacements = confirmed = 0;
    if (!requested) return 1;
    char path[4096];
    if (!fileio_resolve_game("TEX\\ROCKPORT360\\meta.json", path, sizeof path)) goto fail;
    FILE *f = fopen(path, "rb");
    if (!f) goto fail;
    char *json = malloc(JSON_MAX + 1);
    if (!json){ fclose(f); goto fail; }
    size_t n = fread(json, 1, JSON_MAX, f);
    int ok = !ferror(f) && fgetc(f) == EOF;
    fclose(f); json[n] = 0;
    ok = ok && !memchr(json, 0, n) && parse(json);
    free(json);
    if (!ok || !fileio_resolve_game(pack_name, path, sizeof path)) goto fail;
    struct stat st;
    if (stat(path, &st) || st.st_size < 8 || (uint64_t)st.st_size > UINT32_MAX) goto fail;
    f = fopen(path, "rb");
    if (!f) goto fail;
    uint32_t header[2];
    ok = fread(header, 1, sizeof header, f) == sizeof header;
    fclose(f);
    if (!ok || header[0] != 0xb3300000 || (uint64_t)header[1] + 8 > (uint64_t)st.st_size) goto fail;
    pack_bytes = (uint64_t)st.st_size;
    active = 1;
    fprintf(stderr, "[texwizard] %u texture mappings, %llu-byte pack configured\n",
            map_count, (unsigned long long)pack_bytes);
    return (int)map_count;
fail:
    map_count = 0;
    fprintf(stderr, "[texwizard] Cannot configure TEX/ROCKPORT360 texture pack\n");
    return 0;
}

static void load_pack(CPU *c){
    if (resource) return;
    uint32_t name = gheap_alloc(1, sizeof pack_name, 0);
    if (!name){ fprintf(stderr, "[texwizard] Cannot allocate pack path\n"); abort(); }
    memcpy(g_mem + name, pack_name, sizeof pack_name);
    uint32_t args[] = {name, 1, 0, 0, 0};
    CPU save = *c;
    resource = call_guest(c, 0x65FD30, 5, args);
    if (!resource){ fprintf(stderr, "[texwizard] Cannot create pack resource\n"); abort(); }
    *c = save;
    c->ecx = resource;
    uint32_t load_args[] = {0, 0};
    call_guest(c, 0x6616F0, 2, load_args);
    *c = save;
    fprintf(stderr, "[texwizard] Registered %llu-byte texture pack, resource %08x\n",
            (unsigned long long)pack_bytes, resource);
}

int mw_texwizard_hook(CPU *c, uint32_t ip){
    switch (ip){
    case HOOK_SITE(0x00503400):
        if (active){
            uint32_t hash = MR32(c->esp + 4);
            unsigned lo = 0, hi = map_count;
            while (lo < hi){
                unsigned mid = lo + (hi - lo) / 2;
                if (mappings[mid].key < hash) lo = mid + 1; else hi = mid;
            }
            if (lo < map_count && mappings[lo].key == hash){
                uint32_t target = mappings[lo].value;
                MR32(c->esp + 4) = target;
                replacements++;
                uint32_t cached = MR32(0x915198 + (target & 255) * 4);
                if (cached && MR32(cached + 0x24) == target) confirmed++;
            }
        }
        return 1;
    case HOOK_SITE(0x006660C5):
        if (active) load_pack(c);
        return 1;
    default:
        return 0;
    }
}

void mw_texwizard_report(void){
    if (active) fprintf(stderr, "[texwizard] %u mappings, pack registered %s, %llu texture substitutions, %llu confirmed replacement cache hits\n",
            map_count, resource ? "yes" : "no", (unsigned long long)replacements,
            (unsigned long long)confirmed);
}
