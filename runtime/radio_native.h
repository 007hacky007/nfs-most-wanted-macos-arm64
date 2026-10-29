#ifndef NFSU2_RADIO_NATIVE_H
#define NFSU2_RADIO_NATIVE_H
#include "web/radio_proto.h"

typedef struct {
    int enabled, paused, shuffle, tracks;
    char artist[RADIO_TAG], title[RADIO_TAG];
} RadioNativeSnapshot;

/* UI controls only queue state. Guest calls never dispatch to the main queue. */
void radio_native_init(void);
void radio_native_frame(void);
void radio_native_shutdown(void);
void radio_native_set_enabled(int enabled);
void radio_native_set_paused(int paused);
void radio_native_set_shuffle(int shuffle);
void radio_native_next(void);
void radio_native_snapshot(RadioNativeSnapshot *out);

/* Shared radio.c backend. The protocol's 32-bit ring field stays a token on native. */
HostStatusRadio *host_status_radio(void);
void radio_native_lock(void);
void radio_native_unlock(void);
void radio_native_bind_ring(float *ring, uint32_t frames);
int radio_native_paused(void);
void radio_native_track_tags(uint32_t seq, char tags[3][RADIO_TAG]);
#endif
