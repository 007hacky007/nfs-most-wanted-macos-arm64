#include "cpu.h"
#include "hq_audio.h"
#include <CommonCrypto/CommonDigest.h>
/* The pinned ASI's long jump overwrites the zero-quality MOV at 0x4c41ef.
 * The same destination fits a short jump, preserving that original boundary. */
int hq_audio_repair(int force_high_spec){
    /* Before/after repair, each at the two supported low-quality rates. */
    static const char *const accepted[]={
        "365cea4a0a1c204cead254d5d4b23cea0bde3170e5d3c09037e99bb220c60688",
        "1c68b4c62a0162651de1b1df5745fd131d872a41a3a728585cbdff4409031193",
        "4684393cbc35edd63359c953c7c3d5be8b72d9e631fbe67affb663ac42a24b4b",
        "78ad77c945e270986378dd78f3a7b796c8f6fc1b9356fb5c7506be92e060fd18"
    };
    const uint32_t address=0x004c41d7u;
    if(!mem_is_committed(address)||!mem_is_committed(address+33))return 0;
    uint8_t digest[CC_SHA256_DIGEST_LENGTH];char hash[65];
    CC_SHA256(g_mem+address,34,digest);
    static const char hex[]="0123456789abcdef";
    for(unsigned i=0;i<sizeof digest;i++){hash[2*i]=hex[digest[i]>>4];hash[2*i+1]=hex[digest[i]&15];}
    hash[64]=0;unsigned state=0;while(state<4&&strcmp(hash,accepted[state]))state++;
    if(state==4)return 0;
    memcpy(g_mem+address+22,"\xeb\x0a\xc7\x05\x50",5);
    MR32(address+30)=force_high_spec?44100:22050;return 1;
}
