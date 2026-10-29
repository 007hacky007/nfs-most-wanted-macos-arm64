/* Native access to the browser-compatible switch protocol. No connection
 * exists unless NFSU2_NET=online and an explicit player name is supplied. */
#ifndef NFSU2_NET_NATIVE_H
#define NFSU2_NET_NATIVE_H
#include "web/net_proto.h"
#include <stdint.h>
int native_net_enabled(void);
int native_net_url_valid(const char *url);
net_mailbox *native_net_mailbox(uint32_t mode);
void native_net_shutdown(void);
void native_net_wait(int *word, int expected, int64_t ns);
#define __builtin_wasm_memory_atomic_wait32(p, v, ns) native_net_wait((p), (v), (ns))
#define __builtin_wasm_memory_atomic_notify(p, n) ((void)(p), (void)(n))
#endif
