"""Generate guarded native body routing from captured game image variants."""
import argparse
import json
from pathlib import Path
import re


def emit_wrappers(records, output):
    lines = ['#include "cpu.h"', '#include "hq_plugin.h"', '#include "hq_route.h"']
    seen = set()
    for row in sorted(records, key=lambda item: item['entry']):
        entry = row['entry']
        if entry in seen or not 0 <= entry <= 0xffffffff:
            raise ValueError('duplicate or invalid entry')
        seen.add(entry)
        variants = row['variants']
        if not variants:
            raise ValueError('missing baseline variant')
        ranges = row['ranges']
        total = sum(length for address, length in ranges)
        if not total or any(address < 0 or length <= 0 or address + length > 2**32 for address, length in ranges):
            raise ValueError('invalid signature ranges')
        tag = f'{entry:08x}'
        for variant in variants:
            if not re.fullmatch(r'sub_[0-9a-f]{8}_(standard|full[0-9]+)', variant['symbol']):
                raise ValueError('invalid native body symbol')
            signature = bytes.fromhex(variant['bytes'])
            if len(signature) != total:
                raise ValueError('signature size differs from range coverage')
            lines.append(f'void {variant["symbol"]}(CPU *);')
        lines.append(f'static const HQRouteRange r_{tag}[] = {{' + ','.join(f'{{0x{address:08x}u,{length}u}}' for address, length in ranges) + '};')
        for i, variant in enumerate(variants):
            signature = bytes.fromhex(variant['bytes'])
            lines.append(f'static const uint8_t s_{tag}_{i}[] = {{' + ','.join(f'0x{value:02x}' for value in signature) + '};')
        lines.append(f'void sub_{tag}(CPU *c){{')
        lines.append(f' if (!hq_plugin_enabled()){{ {variants[0]["symbol"]}(c); return; }}')
        for i, variant in enumerate(variants):
            lines.append(f' if (hq_route_match(r_{tag}, {len(ranges)}u, s_{tag}_{i})){{ {variant["symbol"]}(c); return; }}')
        lines.append(f' hq_plugin_route_error(c, 0x{tag}u);')
        lines.append('}')
    Path(output).write_text('\n'.join(lines) + '\n', encoding='ascii')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    emit_wrappers(json.loads(args.manifest.read_text())['functions'], args.output)


def emit_native_names(records, extras, output, wrappers=()):
    entries={variant['symbol']:row['entry']for row in records for variant in row['variants']}
    entries.update({f'sub_{entry:08x}':entry for entry in extras})
    entries.update(wrappers)
    lines=['#include "hq_native.h"']
    lines += [f'void {symbol}(CPU*);'for symbol in sorted(entries)]
    lines.append('const HQNativeEntry g_hq_native[]={')
    lines += [f' {{0x{guest:08x}u,{symbol},"{symbol}"}},'for symbol,guest in sorted(entries.items())]
    lines += ['};',f'const unsigned g_hq_native_count={len(entries)}u;']
    Path(output).write_text('\n'.join(lines)+'\n')
