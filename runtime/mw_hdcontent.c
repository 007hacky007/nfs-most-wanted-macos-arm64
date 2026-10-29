/* Correct tightly packed, block-compressed NPOT textures in the HQ pack.
 * TextureInfo+0x40 describes a power-of-two approximation, while +0x38
 * and the payload contain the actual DXT blocks. The original loader divides
 * that approximation by four for every mip, corrupting both copies and offsets.
 * This is separate from Aero's font/cursor/movie scaling adaptations.
 */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#define HOOK_SITE(a) a

static int active;
static int diagnostics;
static unsigned missing_solids;
static unsigned missing_wheels;
static unsigned missing_wheel_solids;
/* The loader is synchronous; key the context to its CPU and guest stack frame
 * so an unrelated hook invocation cannot reuse a previous texture's sizes. */
static _Thread_local struct {
    CPU *cpu;
    uint32_t frame, info, width, height, count, skip, bytes[16];
} texture;

static int readable(uint32_t start, uint32_t bytes){
    if (!start || !bytes || (uint64_t)start + bytes > GSZ) return 0;
    uint64_t end = (uint64_t)start + bytes - 1;
    for (uint64_t p = start & ~16383u; p <= end; p += 16384)
        if (!mem_is_committed((uint32_t)p)) return 0;
    return 1;
}

static void wheel_stream_snapshot(uint32_t render, uint32_t ride, uint32_t hash){
    if (readable(render, 0x1630) && readable(ride, 0x18))
        fprintf(stderr, "[hdcontent] Wheel ranges: ride=%08x render_lods=%u:%u ride_lods=%u:%u/%u:%u\n",
                ride, MR32(render+0x1628), MR32(render+0x162c),
                MR32(ride+8), MR32(ride+12), MR32(ride+16), MR32(ride+20));
    /* Read the manager's pack list and sorted 24-byte stream table directly.
     * The guest lookup moves records in its list, so diagnostics cannot call it. */
    const uint32_t head = 0x0091a078;
    uint32_t record = readable(head, 4) ? MR32(head) : 0;
    unsigned scanned = 0;
    while (record && record != head && scanned < 64 && readable(record, 0x44)){
        scanned++;
        uint32_t table = MR32(record+0x24), count = MR32(record+0x28);
        if (count && count <= 65536 && readable(table, count*24)){
            uint32_t low = 0, high = count;
            while (low < high){
                uint32_t mid = low+(high-low)/2, entry = table+mid*24;
                uint32_t key = MR32(entry);
                if (key < hash) low = mid+1;
                else if (key > hash) high = mid;
                else {
                    fprintf(stderr, "[hdcontent] Wheel stream: hash=%08x stream_record=%08x entry=%08x flags=%02x refs=%u buffer=%08x pending=%u pack_ready=%u pack_disabled=%u\n",
                            hash, record, entry, MR8(entry+0x11), MR16(entry+0x12),
                            MR32(entry+0x14), MR32(record+0x2c), MR32(record+0x14), MR8(record+0xe));
                    uint32_t alignment = MR32(head-0x18), buffer = MR32(entry+0x14);
                    uint32_t tag = 0, payload_hash = 0, initialized = 0, registry = 0;
                    if (alignment && alignment <= 4096 && !(alignment & (alignment-1)) &&
                        (uint64_t)buffer+alignment-1 < GSZ){
                        buffer = (buffer+alignment-1) & ~(alignment-1);
                        if (readable(buffer, 36)){
                            tag = MR32(buffer);
                            if (tag == 0x80134010 && MR32(buffer+8) == 0x134011){
                                payload_hash = MR32(buffer+32); initialized = MR8(buffer+29);
                            }
                        }
                    }
                    uint32_t pack = MR32(record+0x3c);
                    if (readable(pack, 0x78)){
                        uint32_t index = MR32(pack+0x74), n = MR32(pack+12);
                        if (n && n <= 65536 && readable(index, n*8)){
                            uint32_t lo = 0, hi = n;
                            while (lo < hi){
                                uint32_t m = lo+(hi-lo)/2, value = MR32(index+m*8);
                                if (value < hash) lo = m+1;
                                else if (value > hash) hi = m;
                                else {registry = MR32(index+m*8+4); break;}
                            }
                        }
                    }
                    uint32_t bloom = 0x9175dc+(hash & 8191);
                    fprintf(stderr, "[hdcontent] Wheel registration: payload_tag=%08x payload_hash=%08x initialized=%u registry=%08x bloom=%u\n",
                            tag, payload_hash, initialized, registry, readable(bloom, 1) ? MR8(bloom) : 0);
                    return;
                }
            }
        }
        record = MR32(record);
    }
    fprintf(stderr, "[hdcontent] Wheel stream: hash=%08x stream=unresolved scanned=%u\n", hash, scanned);
}

void mw_hdcontent_init(int enabled){
    active = enabled != 0;
    const char *value = getenv("NFSMW_HD_DIAGNOSTICS");
    diagnostics = active && value && !strcmp(value, "1");
    missing_solids = 0;
    missing_wheels = 0;
    missing_wheel_solids = 0;
    memset(&texture, 0, sizeof texture);
}

static void begin(CPU *c){
    memset(&texture, 0, sizeof texture);
    if (!active || !readable(c->ecx, 124)) return;
    uint32_t info = c->ecx, renderer = MR32(info);
    if (!readable(renderer, 32)) return;
    unsigned fmt = MR32(renderer + 0x14), block;
    if (fmt == 0x31545844) block = 8; /* DXT1 */
    else if (fmt == 0x33545844 || fmt == 0x35545844) block = 16;
    else return;
    unsigned w = MR16(info + 0x44), h = MR16(info + 0x46);
    unsigned count = MR8(info + 0x4e);
    if (!w || !h || w > 32767 || h > 32767 || !count || count > 16) return;
    if (!(w & (w - 1)) && !(h & (h - 1))) return;
    unsigned max_dim = w > h ? w : h, max_mips = 1;
    while (max_dim > 1){ max_dim >>= 1; max_mips++; }
    if (count > max_mips) return;
    uint64_t total = 0;
    for (unsigned i = 0; i < count; i++){
        unsigned mw = w >> i, mh = h >> i;
        if (!mw) mw = 1;
        if (!mh) mh = 1;
        texture.bytes[i] = ((mw + 3) / 4) * ((mh + 3) / 4) * block;
        total += texture.bytes[i];
    }
    if (total != MR32(info + 0x38) || !readable(MR32(info + 0x70), (uint32_t)total)) return;
    texture.cpu = c; texture.frame = c->esp - 0x34;
    texture.info = info; texture.width = w; texture.height = h; texture.count = count;
}

int mw_hdcontent_hook(CPU *c, uint32_t ip){
    switch (ip){
    case HOOK_SITE(0x0074f3d1):
        /* Observe the exact missing front wheel immediately before the
         * original light-material call; earlier optional missing parts
         * must not consume this separate diagnostic budget. */
        if (diagnostics && !c->ecx && missing_wheels < 16 && readable(c->esi, 0x88) &&
            readable(c->esp, 8) && c->edi >= c->esi + 0x10ac &&
            c->edi - c->esi - 0x10ac <= 16){
            uint32_t ride = MR32(c->esi + 0x84);
            if (readable(ride, 4)){
                fprintf(stderr, "[hdcontent] Missing front wheel at light-material call: car=%u lod=%u render=%08x wheel_slot=%08x material=%08x\n",
                        MR32(ride), (c->edi - c->esi - 0x10ac) / 4, c->esi,
                        c->edi, MR32(c->esp + 4));
                missing_wheels++;
            }
        }
        return 1;
    case HOOK_SITE(0x0075597c):
        /* Failed eModel initialization in CarRenderInfo's part/LOD loop.
         * Observe the missing solid before the game releases the eModel. */
        if (diagnostics && readable(c->edi, 0x88) &&
            readable(c->esi, 16) && !MR32(c->esi + 12) && readable(c->esp, 0x30)){
            uint32_t ride = MR32(c->edi + 0x84);
            if (readable(ride, 4)){
                uint32_t slot = MR32(c->esp + 0x14);
                if ((slot == 66 || slot == 67) && missing_wheel_solids < 16){
                    fprintf(stderr, "[hdcontent] Missing wheel solid: car=%u hash=%08x slot=%u lod=%u render=%08x model=%08x part=%08x\n",
                            MR32(ride), MR32(c->esp + 0x2c), slot,
                            MR32(c->esp + 0x18), c->edi, c->esi, MR32(c->esp + 0x28));
                    wheel_stream_snapshot(c->edi, ride, MR32(c->esp + 0x2c));
                    missing_wheel_solids++;
                }
                if (missing_solids < 16){
                    fprintf(stderr, "[hdcontent] Missing car solid: car=%u hash=%08x slot=%u lod=%u render=%08x model=%08x\n",
                            MR32(ride), MR32(c->esp + 0x2c), MR32(c->esp + 0x14),
                            MR32(c->esp + 0x18), c->edi, c->esi);
                    missing_solids++;
                }
            }
        }
        return 1;
    case HOOK_SITE(0x006ddd90): begin(c); return 1;
    case HOOK_SITE(0x006ddf2e):
        if (active && texture.cpu == c && texture.frame == c->esp && c->ebp < texture.count){
            texture.skip = c->ebp;
            unsigned w = texture.width >> texture.skip, h = texture.height >> texture.skip;
            MR16(texture.info + 0x44) = w ? w : 1;
            MR16(texture.info + 0x46) = h ? h : 1;
        }
        return 1;
    case HOOK_SITE(0x006ddf94):
        if (active && texture.cpu == c && texture.frame == c->esp && c->ebp <= texture.skip)
            c->eax = texture.bytes[texture.skip - c->ebp];
        return 1;
    case HOOK_SITE(0x006ddfe6):
        if (active && texture.cpu == c && texture.frame == c->esp && c->ebx < texture.count - texture.skip)
            /* EBP also advances the source pointer after UnlockRect. */
            c->ebp = texture.bytes[texture.skip + c->ebx];
        return 1;
    default: return 0;
    }
}
