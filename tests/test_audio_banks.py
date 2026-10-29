import struct
import os
import subprocess
import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from tools.prepare_audio_callbacks import extract_bank, prepare, verify_helper_entries
from tools.lift_callbacks import callback, emit, _emit_local
from tools.lift import RawLifter

HELPERS = tuple(0x401000 + i * 16 for i in range(40))


def fixture(code=None, duplicate=False):
    code = code or bytes.fromhex('568b74240856e80000000083c4045ec3')
    entry = 0x9c
    module_data = (entry + len(code) + 7) & ~7
    control_end = module_data + 0x20
    call_table = control_end + 8
    call_count = 2 if duplicate else 1
    pointer_table = call_table + 4 + call_count * 4
    export_table = pointer_table + 8
    data = bytearray(export_table + 4)
    data[:8] = b'ABKC\x01\x01\x01\0'
    struct.pack_into('<H', data, 0xa, 1)
    def put(offset, value): struct.pack_into('<I', data, offset, value)
    for offset, value in [(0x14, len(data)), (0x18, control_end), (0x1c, 0x5c),
                          (0x20, control_end), (0x24, 8), (0x30, call_table),
                          (0x34, pointer_table), (0x38, export_table),
                          (0x5c + 0x28, entry), (0x5c + 0x2c, module_data),
                          (0x5c + 0x30, 0x20), (call_table, call_count),
                          (pointer_table, 1), (pointer_table + 4, module_data),
                          (module_data, module_data + 4)]: put(offset, value)
    data[0x5c + 0x24] = 1
    data[entry:entry + len(code)] = code
    for i in range(call_count): put(call_table + 4 + i * 4, entry + code.index(0xe8) + 1)
    data[control_end:control_end + 4] = b'BNKl'
    return data


class AudioBankTests(unittest.TestCase):
    def test_metadata_declared_body_matches_relocated_runtime_template(self):
        data = fixture()
        records = extract_bank(bytes(data), HELPERS)
        self.assertEqual(len(records), 1)
        entry = 0x9c
        runtime = bytearray(data[entry:entry + 16])
        struct.pack_into('<i', runtime, 7, HELPERS[0] - (0x50000 + 11))
        expected = callback(runtime, 0x50000)
        self.assertEqual(records[0]['key'], expected['key'])
        self.assertEqual(records[0]['calls'][0][3], HELPERS[0])
        self.assertEqual(records[0]['bank_offset'], entry)

    def test_malformed_sections_relocations_and_helper_indices_are_refused(self):
        mutations = [
            ('wrong version', lambda b: b.__setitem__(4, 2)),
            ('wrong size', lambda b: struct.pack_into('<I', b, 0x14, len(b) + 1)),
            ('module outside control', lambda b: struct.pack_into('<I', b, 0x1c, len(b))),
            ('constructor in data', lambda b: struct.pack_into('<I', b, 0x84, 0xb0)),
            ('invalid helper', lambda b: struct.pack_into('<I', b, 0xa3, 40)),
            ('relocation not call operand', lambda b: struct.pack_into('<I', b, struct.unpack_from('<I', b, 0x30)[0] + 4, 0xa4)),
            ('pointer field in code', lambda b: struct.pack_into('<I', b, struct.unpack_from('<I', b, 0x34)[0] + 4, 0xa0)),
            ('pointer target outside control', lambda b: struct.pack_into('<I', b, 0xb0, len(b))),
            ('nonzero code padding', lambda b: b.__setitem__(0xac, 0x90)),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                data = fixture(); mutate(data)
                with self.assertRaises(ValueError): extract_bank(bytes(data), HELPERS)
        with self.assertRaises(ValueError): extract_bank(bytes(fixture(duplicate=True)), HELPERS)

    def test_equivalent_decoded_entry_encoding_is_accepted(self):
        code = bytes.fromhex('568bb4240800000056e80000000083c4045ec3')
        records = extract_bank(bytes(fixture(code)), HELPERS)
        self.assertEqual(len(records), 1)

    def test_committable_output_is_rejected_before_reading_or_writing(self):
        output = Path(__file__).resolve().parents[1] / 'runtime' / 'audio-test-generated'
        self.assertFalse(output.exists())
        with patch('tools.prepare_audio_callbacks.helper_targets', side_effect=AssertionError('input read before output validation')):
            with self.assertRaisesRegex(ValueError, 'ignored'):
                prepare(Path('unused'), Path('unused'), output)
        self.assertFalse(output.exists())

    def test_emit_refuses_traps_or_truncated_cfg_without_changing_output(self):
        record = extract_bank(bytes(fixture()), HELPERS)[0]
        code, _ = RawLifter(bytes.fromhex(record['bytes']), base=record['base'], comments=False).lift(record['base'])
        for traps, truncated in ((1, 0), (0, 1)):
            with self.subTest(traps=traps, truncated=truncated), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'callbacks.c'; output.write_text('original')
                lifter = SimpleNamespace(traps=traps, truncated=truncated,
                                         lift=lambda entry: (code, set()))
                with patch('tools.lift_callbacks.RawLifter', return_value=lifter):
                    with self.assertRaises(ValueError): _emit_local([record], output)
                self.assertEqual(output.read_text(), 'original')

    def test_native_helper_address_and_pointer_arrays_must_agree(self):
        table = 'const unsigned g_fn_addr[]={0x401000u}; const guest_fn g_fn_ptr[]={sub_00401000};'
        verify_helper_entries([0x401000], table)
        for helpers, text in (([0x401010], table), ([0x401000], table.replace('sub_00401000', 'sub_00401010'))):
            with self.assertRaises(ValueError): verify_helper_entries(helpers, text)

    def test_bad_bank_does_not_replace_prepared_output(self):
        with tempfile.TemporaryDirectory() as tmp, patch('tools.prepare_audio_callbacks._canonical_helpers', return_value=HELPERS):
            root = Path(tmp); sound = root / 'game' / 'sound'; sound.mkdir(parents=True)
            (root / 'runtime.exe').write_bytes(b'runtime fixture'); (root / 'fntab.c').write_text('native table fixture')
            (sound / 'test.abk').write_bytes(fixture()); output = root / 'prepared'
            first = prepare(root / 'game', root / 'runtime.exe', output, root / 'fntab.c')
            self.assertEqual(first['templates'], 1)
            before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            (sound / 'bad.abk').write_bytes(b'bad')
            with self.assertRaises(ValueError): prepare(root / 'game', root / 'runtime.exe', output, root / 'fntab.c')
            self.assertEqual(before, {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()})

    def test_overlapping_module_data_ranges_are_refused(self):
        def two_modules(second_data):
            data = bytearray(0x15c)
            data[:8] = b'ABKC\x01\x01\x01\0'
            struct.pack_into('<H', data, 0xa, 2)
            fields = [(0x14, len(data)), (0x18, 0x140), (0x1c, 0x5c),
                      (0x20, 0x140), (0x24, 8), (0x30, 0x148), (0x34, 0x154), (0x38, 0x158),
                      (0x148, 2), (0x14c, 0xe3), (0x150, 0xf3)]
            for module, entry, start in [(0x5c, 0xdc, 0x100), (0x9c, 0xec, second_data)]:
                data[module + 0x24] = 1
                fields += [(module + 0x28, entry), (module + 0x2c, start), (module + 0x30, 0x20)]
                data[entry:entry + 16] = bytes.fromhex('568b74240856e80000000083c4045ec3')
            for offset, value in fields: struct.pack_into('<I', data, offset, value)
            data[0x140:0x144] = b'BNKl'
            return bytes(data)
        self.assertEqual(len(extract_bank(two_modules(0x120), HELPERS)), 2)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            extract_bank(two_modules(0x110), HELPERS)

    def test_inherited_generation_flags_cannot_change_return_or_source(self):
        record = extract_bank(bytes(fixture()), HELPERS)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); normal = root / 'normal.c'; hostile = root / 'hostile.c'
            emit([record], normal)
            profiles = [{'RETEIP': '0'}, {'RETEIP': '0', 'LREGS': '1', 'JTSWITCH': '1', 'FLAGOPT': '0',
                         'FTOL2INL': '1', 'X87PC': '0', 'X87OPT': '1',
                         'FLAGABI': 'missing-callback-abi.json', 'INLINE_LIST': 'missing-callback-inline.txt'}]
            for profile in profiles:
                with patch.dict(os.environ, profile): emit([record], hostile)
                self.assertEqual(normal.read_bytes(), hostile.read_bytes())
            (root / 'test.c').write_text("""#include "cpu.h"
#include <assert.h>
#include <stdlib.h>
uint8_t *g_mem;uint8_t g_cbits[1u<<15];int native_generated_call(CPU*,uint32_t);
void dispatch_indirect(CPU*c,uint32_t target){assert(target==0x401000);POP32(c->eip);c->eax=42;}
int main(void){g_mem=calloc(1,65536);g_cbits[0]=15;CPU cpu={0},*c=&cpu;
unsigned char code[]={0x56,0x8b,0x74,0x24,8,0x56,0xe8,0,0,0,0,0x83,0xc4,4,0x5e,0xc3};
memcpy(g_mem+0x1000,code,sizeof code);MR32(0x1007)=0x401000-(0x1000+11);
c->esp=0x5000;c->esi=0x123456;MR32(c->esp)=0xbeef;MR32(c->esp+4)=0x2000;
assert(native_generated_call(c,0x1000));assert(c->esp==0x5004&&c->eip==0xbeef&&c->esi==0x123456&&c->eax==42);free(g_mem);}
""")
            subprocess.run(['clang', '-O1', '-fno-strict-aliasing', '-Iruntime', str(root / 'test.c'), str(hostile), '-lm', '-o', str(root / 'test')], check=True, capture_output=True)
            subprocess.run([str(root / 'test')], check=True, capture_output=True)

    def test_output_modified_during_emit_is_preserved(self):
        from tools import prepare_audio_callbacks as tool
        original_emit = tool.emit
        with tempfile.TemporaryDirectory() as tmp, patch.object(tool, '_canonical_helpers', return_value=HELPERS):
            root = Path(tmp); sound = root / 'game' / 'sound'; sound.mkdir(parents=True)
            (root / 'runtime.exe').write_bytes(b'runtime fixture'); (root / 'fntab.c').write_text('native table fixture')
            (sound / 'test.abk').write_bytes(fixture()); output = root / 'prepared'
            prepare(root / 'game', root / 'runtime.exe', output, root / 'fntab.c')
            def change(records, destination):
                original_emit(records, destination)
                (output / 'unmanaged-note.txt').write_text('keep')
            with patch.object(tool, 'emit', side_effect=change):
                with self.assertRaises(ValueError): prepare(root / 'game', root / 'runtime.exe', output, root / 'fntab.c')
            self.assertEqual((output / 'unmanaged-note.txt').read_text(), 'keep')

    def test_input_changes_during_generation_do_not_replace_output(self):
        from tools import prepare_audio_callbacks as tool
        original_emit = tool.emit
        for change_kind in ('bank', 'runtime', 'native table', 'new bank'):
            with self.subTest(change=change_kind), tempfile.TemporaryDirectory() as tmp, patch.object(tool, '_canonical_helpers', return_value=HELPERS):
                root = Path(tmp); sound = root / 'game' / 'sound'; sound.mkdir(parents=True)
                bank = sound / 'test.abk'; bank.write_bytes(fixture())
                runtime = root / 'runtime.exe'; runtime.write_bytes(b'runtime fixture')
                table = root / 'fntab.c'; table.write_text('native table fixture')
                output = root / 'prepared'; prepare(root / 'game', runtime, output, table)
                before = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
                def change(records, destination):
                    original_emit(records, destination)
                    if change_kind == 'new bank': (sound / 'new.abk').write_bytes(fixture())
                    else:
                        target = {'bank': bank, 'runtime': runtime, 'native table': table}[change_kind]
                        target.write_bytes(target.read_bytes() + b'changed')
                with patch.object(tool, 'emit', side_effect=change):
                    with self.assertRaisesRegex(ValueError, 'changed'):
                        prepare(root / 'game', runtime, output, table)
                self.assertEqual(before, {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()})

    def test_backward_branch_or_missing_return_is_refused(self):
        for tail in ('ebfe', '9090'):
            code = bytes.fromhex('568b74240856e80000000083c4045e' + tail)
            with self.assertRaises(ValueError): extract_bank(bytes(fixture(code)), HELPERS)


if __name__ == '__main__': unittest.main()
