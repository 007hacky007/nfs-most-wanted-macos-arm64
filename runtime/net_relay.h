/* Donor virtual-LAN backend on the native switch transport. */
#ifndef NFSU2_NET_RELAY_H
#define NFSU2_NET_RELAY_H
#include "winsock.h"
#include "web/lan_vfd.h"
int  relay_vlan_hello(const char *path, NetIdent *id);       /* 0 or WSA error */
int  relay_vlan_open(WsSock *s);
int  relay_vlan_bind(WsSock *s, uint32_t ip, uint16_t port);
int  relay_vlan_connect(WsSock *s, uint32_t ip, uint16_t port);
int  relay_vlan_listen(WsSock *s, int backlog);
int  relay_vlan_accept(WsSock *ls, WsSock *ns);
int  relay_vlan_sendto(WsSock *s, const uint8_t *buf, int len, uint32_t ip, uint16_t port, int *sent);
int  relay_vlan_recvfrom(WsSock *s, uint8_t *buf, int len, int peek, uint32_t *ip, uint16_t *port, int *got);
void relay_vlan_close(WsSock *s, int abortive);
int  relay_vlan_conn_was_reset(WsSock *s);
void relay_vlan_note(const char *text);                       /* marker line in the hub log */
int  relay_vlan_alive(void);
void relay_vlan_session_end(void);                            /* the last WSACleanup: no network session now */

void relay_vlan_conn_update(WsSock *s);
void relay_vlan_fionread(WsSock *s, uint32_t *v);
void relay_vlan_report(void);
#endif
