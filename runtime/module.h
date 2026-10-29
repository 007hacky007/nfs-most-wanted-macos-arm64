/* Fingerprinted guest PE modules and native AOT dispatch. */
#ifndef MODULE_H
#define MODULE_H
#include <stdint.h>

typedef struct {
    const char *name;         /* lower-case file name, "" = not lifted into this build */
    const char *sha256;       /* of the original file the code was lifted from */
    uint32_t base;            /* guest base the code was lifted for */
    uint32_t pref;            /* the file's preferred ImageBase */
    uint32_t size;            /* SizeOfImage */
    uint32_t entry;           /* _DllMainCRTStartup, at base */
    uint32_t text, text_size; /* .text at base */
    uint32_t file_size;
} ModInfo;

struct CPU;
/* Module handles are the base addresses (as on Windows). */
uint32_t module_load(struct CPU *c, const char *name, uint32_t *err);  /* LoadLibraryA */
int      module_free(struct CPU *c, uint32_t h);                       /* FreeLibrary; 0 = not a module */
int      module_handle(uint32_t h);                    /* h is a lifted module (mapped or not) */
uint32_t module_by_name(const char *name);             /* GetModuleHandleA: base if mapped, else 0 */
int      module_known_name(const char *name);          /* name is a lifted module, mapped or not */
uint32_t module_proc(uint32_t h, uint32_t name_or_ord, uint32_t *err);  /* GetProcAddress */
int      module_file_name(uint32_t h, char *out, int n);                /* GetModuleFileNameA */
/* Import namespaces: game = 0, generated catalog entries = 1..module_count(). */
int module_count(void);
const void *module_imports(int id,uint32_t *count);
uint32_t module_from_address(uint32_t address);
int module_static_tls(uint32_t base,uint32_t *data,uint32_t *size,uint32_t *index,uint32_t *slot);
uint32_t module_imp_first(int m);
int      module_of_import(uint32_t idx);
/* dispatch.c: lifted function at a module address, or 0 */
typedef void (*mod_fn)(struct CPU *);
mod_fn   module_fn_at(uint32_t addr);
uint32_t module_nearest_fn(uint32_t addr, const char **mod);  /* backtraces */
uint32_t module_fn_from_host(const void *pc);
void     module_report(void);
#endif
