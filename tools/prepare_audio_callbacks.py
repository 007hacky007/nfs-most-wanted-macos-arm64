#!/usr/bin/env python3
"""Prepare bounded native audio callbacks from the supplied PC ABKC banks."""
import argparse
import hashlib
import json
from itertools import islice
from pathlib import Path
import re
import struct
import tempfile

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86 import X86_OP_REG, X86_OP_MEM, X86_OP_IMM, X86_REG_ESI, X86_REG_ESP
try:
    from .lift_callbacks import callback, emit, GENERATION_PROFILE
    from .prepare_hq_modules import checked_output
except ImportError:
    from lift_callbacks import callback, emit, GENERATION_PROFILE
    from prepare_hq_modules import checked_output

RUNTIME_SHA256 = '80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c'
HELPER_TABLE = 0x90bc40
HELPER_COUNT = 40


def digest(data):
    return hashlib.sha256(data).hexdigest()


def helper_targets(runtime, fntab):
    return _canonical_helpers(Path(runtime).read_bytes(), Path(fntab).read_text())


def _canonical_helpers(data, table):
    if digest(data) != RUNTIME_SHA256:
        raise ValueError('unsupported audio runtime image')
    image = pefile.PE(data=data)
    raw = image.get_data(HELPER_TABLE - image.OPTIONAL_HEADER.ImageBase, HELPER_COUNT * 4)
    if len(raw) != HELPER_COUNT * 4:
        raise ValueError('truncated audio helper table')
    helpers = struct.unpack('<40I', raw)
    code = [(image.OPTIONAL_HEADER.ImageBase + s.VirtualAddress,
             image.OPTIONAL_HEADER.ImageBase + s.VirtualAddress + s.Misc_VirtualSize)
            for s in image.sections if s.Characteristics & 0x20]
    if any(not any(a <= target < b for a, b in code) for target in helpers):
        raise ValueError('audio helper is outside executable image sections')
    verify_helper_entries(helpers, table)
    return helpers


def verify_helper_entries(helpers, text):
    addresses = re.search(r'\bg_fn_addr\s*\[\s*\]\s*=\s*\{([^}]+)\}', text, re.S)
    functions = re.search(r'\bg_fn_ptr\s*\[\s*\]\s*=\s*\{([^}]+)\}', text, re.S)
    if not addresses or not functions:
        raise ValueError('missing native function table')
    entries = [int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]+)u?', addresses.group(1))]
    names = [int(x, 16) for x in re.findall(r'\bsub_([0-9a-fA-F]{8})\b', functions.group(1))]
    if entries != names:
        raise ValueError('native address/function table mismatch')
    missing = sorted(set(helpers) - set(entries))
    if missing:
        raise ValueError('audio helper lacks native function entry: ' + ', '.join(f'{x:08x}' for x in missing))


def abi_entry(instructions):
    if len(instructions) != 4:
        return False
    def push_esi(insn):
        return (insn.mnemonic == 'push' and len(insn.operands) == 1 and
                insn.operands[0].type == X86_OP_REG and insn.operands[0].reg == X86_REG_ESI and insn.operands[0].size == 4)
    first, load, argument, call = instructions
    if not push_esi(first) or not push_esi(argument) or load.mnemonic != 'mov' or len(load.operands) != 2:
        return False
    dest, source = load.operands
    return (dest.type == X86_OP_REG and dest.reg == X86_REG_ESI and dest.size == 4 and
            source.type == X86_OP_MEM and source.size == 4 and source.mem.base == X86_REG_ESP and
            not source.mem.index and not source.mem.segment and source.mem.disp == 8 and
            call.mnemonic == 'call' and len(call.operands) == 1 and call.operands[0].type == X86_OP_IMM)


def extract_bank(data, helpers):
    """Validate one PC bank and return exact templates with relocated CALL operands."""
    def bounds(offset, size, end=None):
        if offset < 0 or size < 0 or offset + size > (len(data) if end is None else end):
            raise ValueError('ABKC section outside declared bounds')
    def u32(offset):
        bounds(offset, 4)
        return struct.unpack_from('<I', data, offset)[0]
    bounds(0, 0x5c)
    if data[:8] != b'ABKC\x01\x01\x01\0' or u32(0x14) != len(data):
        raise ValueError('unsupported or truncated PC ABKC bank')
    if len(helpers) != HELPER_COUNT:
        raise ValueError('invalid canonical helper table')
    control_end, modules = u32(0x18), u32(0x1c)
    if modules < 0x5c or modules & 3 or control_end > len(data):
        raise ValueError('invalid ABKC control section')
    count = struct.unpack_from('<H', data, 0xa)[0]
    if not count:
        raise ValueError('ABKC bank has no declared modules')
    cursor = modules
    entries, ranges = [], []
    for _ in range(count):
        bounds(cursor, 0x3c, control_end)
        entry, start, size = u32(cursor + 0x28), u32(cursor + 0x2c), u32(cursor + 0x30)
        bounds(start, size, control_end)
        if not start or not size:
            raise ValueError('empty ABKC module data')
        entries.append(entry)
        ranges.append((start, start + size))
        cursor += 0x3c + 4 * (data[cursor + 0x24] + data[cursor + 0x27])
        bounds(cursor, 0, control_end)
    code_end = min(start for start, _ in ranges)
    if len(set(entries)) != count or min(entries) != cursor or any(not cursor <= e < code_end for e in entries):
        raise ValueError('ABKC constructor overlaps module headers or data')
    ordered_ranges = sorted(ranges)
    if any(a[1] > b[0] for a, b in zip(ordered_ranges, ordered_ranges[1:])):
        raise ValueError('ABKC module data ranges overlap')
    sample, sample_size = u32(0x20), u32(0x24)
    if sample_size:
        if sample != control_end:
            raise ValueError('ABKC samples overlap control data')
        bounds(sample, sample_size)
        if data[sample:sample + 4] not in (b'BNKl', b'BNKb'):
            raise ValueError('invalid ABKC sample section')
    elif sample not in (0, control_end):
        raise ValueError('invalid empty ABKC sample section')
    call_table, pointer_table, export_table = u32(0x30), u32(0x34), u32(0x38)
    if not control_end + sample_size <= call_table <= pointer_table <= export_table < len(data):
        raise ValueError('invalid ABKC relocation section order')
    def relocations(table, limit):
        number = u32(table)
        bounds(table + 4, number * 4, limit)
        if table + 4 + number * 4 != limit:
            raise ValueError('ABKC relocation table boundary mismatch')
        fields = [u32(table + 4 + i * 4) for i in range(number)]
        if len(set(fields)) != len(fields):
            raise ValueError('duplicate ABKC relocation')
        return fields
    calls = set(relocations(call_table, pointer_table))
    pointers = relocations(pointer_table, export_table)
    for field in pointers:
        # The original loader adds the bank base here. Such a relocation in
        # code would invalidate the exact non-CALL bytes used by the matcher.
        if field < code_end or field & 3:
            raise ValueError('ABKC pointer relocation overlaps constructor code')
        bounds(field, 4, control_end)
        if u32(field) >= control_end:
            raise ValueError('ABKC pointer target outside control data')
    exports = u32(export_table)
    bounds(export_table + 4, exports * 12)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    result, observed = [], set()
    ordered = sorted(entries)
    for entry, end in zip(ordered, ordered[1:] + [code_end]):
        buffer = bytearray(data[entry:end])
        base, length = 0x10000000, 0
        if not abi_entry(list(islice(md.disasm(bytes(buffer), base), 4))):
            raise ValueError('unsupported ABKC constructor ABI entry')
        for insn in md.disasm(bytes(buffer), base):
            if insn.address != base + length:
                raise ValueError('non-contiguous ABKC constructor')
            length += insn.size
            if insn.mnemonic == 'call':
                if insn.imm_size != 4 or insn.bytes[0] != 0xe8:
                    raise ValueError('unsupported ABKC call instruction')
                position = insn.address - base + insn.imm_offset
                field = entry + position
                if field not in calls:
                    raise ValueError('ABKC call lacks relocation metadata')
                index = u32(field)
                if index >= len(helpers):
                    raise ValueError('ABKC helper index outside canonical table')
                observed.add(field)
                struct.pack_into('<i', buffer, position, helpers[index] - (insn.address + insn.size))
            if insn.mnemonic == 'ret':
                break
        else:
            raise ValueError('ABKC constructor has no bounded return')
        padding = buffer[length:]
        if len(padding) > 7 or any(padding):
            raise ValueError('ABKC constructor has unexplained trailing code')
        record = callback(bytes(buffer[:length]), base)
        record['bank_offset'] = entry
        result.append(record)
    if observed != calls:
        raise ValueError('ABKC relocation does not identify a constructor CALL operand')
    return result


def _bank_inputs(root):
    sounds = [p for p in root.iterdir() if p.name.casefold() == 'sound' and p.is_dir()]
    if len(sounds) != 1:
        raise ValueError('game root must contain one sound directory')
    result = []
    for path in sorted(sounds[0].rglob('*')):
        if path.suffix.casefold() != '.abk':
            continue
        ancestor = path
        while ancestor != root:
            if ancestor.is_symlink():
                raise ValueError('audio bank symlink is not supported')
            ancestor = ancestor.parent
        result.append((path, path.read_bytes()))
    if not result:
        raise ValueError('no ABKC audio banks found')
    return result


def _output_state(output):
    if output.is_symlink():
        raise ValueError('audio callback output cannot be a symlink')
    if not output.exists():
        return None
    try:
        marker = (output / 'manifest.json').read_bytes()
        managed = json.loads(marker)
        if any(p.is_symlink() for p in output.rglob('*')):
            raise ValueError('audio callback output contains a symlink')
        expected = set(managed['files']) | {'manifest.json'}
        actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
        if managed.get('kind') != 'native-audio-callbacks' or actual != expected:
            raise ValueError('unmanaged audio callback output')
        for name, sha in managed['files'].items():
            if digest((output / name).read_bytes()) != sha:
                raise ValueError('modified audio callback output')
        return digest(marker)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('unmanaged audio callback output') from error


def _processors():
    return {name: digest(Path(__file__).with_name(name).read_bytes())
            for name in ('prepare_audio_callbacks.py', 'lift_callbacks.py', 'lift.py', 'prepare_hq_modules.py')}


def prepare(game_root, runtime, output=Path('out/audio-callbacks'), fntab=Path('gen/all/fntab.c')):
    if Path(output).is_symlink():
        raise ValueError('audio callback output cannot be a symlink')
    output = checked_output(output)
    original_output = _output_state(output)
    runtime_data, table_data = Path(runtime).read_bytes(), Path(fntab).read_bytes()
    helpers = _canonical_helpers(runtime_data, table_data.decode())
    runtime_hash, table_hash = digest(runtime_data), digest(table_data)
    processors = _processors()
    root = Path(game_root).resolve()
    inputs, records, constructors = [], {}, 0
    for path, data in _bank_inputs(root):
        bank = extract_bank(data, helpers)
        inputs.append({'path': path.relative_to(root).as_posix(), 'sha256': digest(data)})
        constructors += len(bank)
        for record in bank:
            previous = records.setdefault(record['key'], record)
            if previous['mask'] != record['mask'] or any((a ^ b) & m for a, b, m in zip(
                    bytes.fromhex(previous['bytes']), bytes.fromhex(record['bytes']), bytes.fromhex(record['mask']))):
                raise ValueError('audio template key collision')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.audio-prepare-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'prepared'
        (stage / 'records').mkdir(parents=True)
        selected = [records[key] for key in sorted(records)]
        emit(selected, stage / 'callbacks.c')
        for record in selected:
            (stage / 'records' / (record['key'] + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        manifest = {'kind': 'native-audio-callbacks', 'version': 1, 'runtime_sha256': runtime_hash,
                    'native_table_sha256': table_hash, 'processors': processors,
                    'generation_profile': dict(GENERATION_PROFILE), 'helpers': list(helpers), 'inputs': inputs,
                    'banks': len(inputs), 'constructors': constructors, 'templates': len(records),
                    'source': 'callbacks.c',
                    'files': {p.relative_to(stage).as_posix(): digest(p.read_bytes())
                              for p in sorted(stage.rglob('*')) if p.is_file()}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Validate the exact snapshots used to generate the output, then check
        # the destination again before replacing anything another writer owns.
        if digest(Path(runtime).read_bytes()) != runtime_hash or digest(Path(fntab).read_bytes()) != table_hash:
            raise ValueError('audio runtime or native table changed during preparation')
        current = [{'path': p.relative_to(root).as_posix(), 'sha256': digest(data)} for p, data in _bank_inputs(root)]
        if Path(game_root).resolve() != root or current != inputs or _processors() != processors:
            raise ValueError('audio inputs or processors changed during preparation')
        if _output_state(output) != original_output:
            raise ValueError('audio callback output changed during preparation')
        old = Path(temporary) / 'previous'
        if output.exists():
            output.rename(old)
        try:
            stage.rename(output)
        except OSError:
            if old.exists():
                old.rename(output)
            raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--fntab', type=Path, default=Path('gen/all/fntab.c'))
    parser.add_argument('--output', type=Path, default=Path('out/audio-callbacks'))
    args = parser.parse_args()
    result = prepare(args.game, args.runtime, args.output, args.fntab)
    print(f"Prepared {result['templates']} native templates from {result['banks']} audio banks")


if __name__ == '__main__':
    main()
