"""Bounded phase preparation keeps source data private and publication transactional."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_hq_phases as phases

ROOT = Path(__file__).resolve().parents[1]


class HQPhaseTests(unittest.TestCase):
    def test_unverified_baseline_cannot_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / 'baseline.bin'
            baseline.write_bytes(b'unknown')
            output = root / 'prepared'
            for digest in ('', '0' * 64):
                with self.subTest(digest=digest), self.assertRaises(ValueError):
                    phases.prepare_phases(root / 'game', baseline, output, baseline_sha256=digest)
                self.assertFalse(output.exists())

    def test_snapshot_validator_refuses_truncation_and_unexpected_game_writes(self):
        baseline = bytes(phases.GAME_SIZE)
        with self.assertRaisesRegex(ValueError, 'complete'):
            phases._ranges(baseline, baseline[:-1], phases.CALLBACK_RANGES)
        modified = bytearray(baseline)
        modified[0x1234] = 1
        with self.assertRaisesRegex(ValueError, 'outside'):
            phases._ranges(baseline, modified, phases.CALLBACK_RANGES)
        modified[0x1234] = 0
        modified[0x005a30b2 - phases.GAME_BASE] = 1
        self.assertEqual(phases._ranges(baseline, modified, phases.CALLBACK_RANGES), [[0x005a30b2, 1]])

    def test_unknown_output_and_symlinks_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'prepared'
            output.mkdir()
            (output / 'keep').write_bytes(b'untouched')
            with self.assertRaises(ValueError):
                phases.prepare_phases(root / 'game', root / 'memory', output, baseline_sha256='0' * 64)
            self.assertEqual((output / 'keep').read_bytes(), b'untouched')
            link = root / 'link'
            link.symlink_to(root / 'missing', target_is_directory=True)
            with self.assertRaises(ValueError):
                phases.prepare_phases(root / 'game', root / 'memory', link, baseline_sha256='0' * 64)
            self.assertTrue(link.is_symlink())

    def test_native_models_reject_unknown_callers_sizes_and_invalid_frames(self):
        if sys.platform != 'darwin':
            self.skipTest('requires the native ARM64 CPU headers')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'generated.h').write_text('void sub_01007b30(CPU*);\nvoid sub_01013660(CPU*);\n')
            (root / 'test.c').write_text(r'''#define main phase_driver_main
#include "hq_phase_driver.c"
#undef main
#include <assert.h>
void sub_01007b30(CPU*c){(void)c;}
void sub_01013660(CPU*c){(void)c;}
int main(int argc,char**argv){
 g_mem=calloc(1,0x08000000);assert(g_mem);CPU cpu={0},*c=&cpu;c->esp=0x00eef000;
 unsigned scenario=(unsigned)atoi(argv[1]);heap_next=0x04000000;
 MR32(c->esp)=0x0101374a;MR32(c->esp+4)=20;
 if(scenario==1)MR32(c->esp)=0x0101374b;
 if(scenario==2)MR32(c->esp+4)=21;
 if(scenario==3)c->esp=0x08000000;
 if(scenario==4)dispatch_indirect(c,0x01234567);
 if(scenario==5){MR32(c->esp)=0x01111111;MR32(c->esp+4)=0x642eaf;MR32(c->esp+8)=5;MR32(c->esp+12)=0x40;MR32(c->esp+16)=c->esp+64;dispatch_indirect(c,0xf0000000);return 0;}
 dispatch_indirect(c,0x004653d0);
 assert(!scenario&&c->eax==0x04000000&&c->esp==0x00eef004&&c->eip==0x0101374a);
 c->esp=0x00eef000;MR32(c->esp)=0x010138bf;MR32(c->esp+4)=MR32(c->esp+8)=0;c->ecx=0;
 dispatch_indirect(c,0x006616f0);assert(c->esp==0x00eef00c&&c->eip==0x010138bf);
 puts("native model boundaries passed");free(g_mem);return 0;
}
''')
            binary = root / 'test'
            compiled = subprocess.run(['clang', '-O1', '-I' + str(ROOT / 'tools'),
                                       '-I' + str(ROOT / 'runtime'), '-I' + str(root),
                                       str(root / 'test.c'), str(ROOT / 'runtime/hq_config.c'),
                                       '-lm', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            for scenario in range(6):
                result = subprocess.run([str(binary), str(scenario)], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0 if scenario == 0 else 77, result.stderr)

    def test_failed_execution_changed_inputs_and_publication_restore_previous_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            game = root / 'game';game.mkdir()
            inputs = {}
            for key in ('baseline', 'canonical', 'module', 'config'):
                path = root / (key + '.input');path.write_bytes(key.encode());inputs[key] = path
            output = root / 'output';output.mkdir()
            (output / phases.MARKER).write_text(json.dumps({'producer': 'hq-phases', 'version': 1}))
            (output / 'keep').write_bytes(b'old valid output')
            def generate(module, staged):
                (staged / 'generated.c').write_text('/* synthetic preparation fixture */')
            def execute(staged):
                for name in ('callback', 'render'):
                    (staged / (name + '.game.bin')).write_bytes(b'synthetic')
            def snapshots(staged, canonical):
                return [{'phase': name, 'file': name + '.game.bin', 'size': 9,
                         'sha256': hashlib.sha256(b'synthetic').hexdigest(), 'changed_ranges': []}
                        for name in ('callback', 'render')]
            with patch.object(phases, '_inputs', return_value=inputs), patch.object(phases, '_generate', side_effect=generate), patch.object(phases, '_snapshots', side_effect=snapshots):
                with patch.object(phases, '_run', side_effect=ValueError('bounded driver failure')):
                    with self.assertRaisesRegex(ValueError, 'driver failure'):
                        phases.prepare_phases(game, inputs['baseline'], output, baseline_sha256='0' * 64)
                    self.assertEqual((output / 'keep').read_bytes(), b'old valid output')
                def mutate(staged):
                    execute(staged);inputs['module'].write_bytes(b'changed module')
                with patch.object(phases, '_run', side_effect=mutate):
                    with self.assertRaisesRegex(ValueError, 'changed'):
                        phases.prepare_phases(game, inputs['baseline'], output, baseline_sha256='0' * 64)
                    self.assertTrue((output / 'keep').is_file())
                rename = Path.rename
                def fail_publish(path, destination):
                    if path.name == 'prepared' and Path(destination) == output:
                        raise OSError('injected publication failure')
                    return rename(path, destination)
                with patch.object(phases, '_run', side_effect=execute), patch.object(Path, 'rename', fail_publish):
                    with self.assertRaisesRegex(OSError, 'publication failure'):
                        phases.prepare_phases(game, inputs['baseline'], output, baseline_sha256='0' * 64)
                    self.assertEqual((output / 'keep').read_bytes(), b'old valid output')
                with patch.object(phases, '_run', side_effect=execute):
                    paths = phases.prepare_phases(game, inputs['baseline'], output, baseline_sha256='0' * 64)
                self.assertEqual([p.read_bytes() for p in paths], [b'synthetic', b'synthetic'])
                record = json.loads((output / phases.MARKER).read_text())
                self.assertNotIn(str(root), json.dumps(record))
                self.assertFalse((output / 'keep').exists())

    @unittest.skipUnless(os.environ.get('NFSMW_HQ_PHASE_GAME'), 'set NFSMW_HQ_PHASE_GAME for locally generated original instruction checks')
    def test_actual_module_writes_are_bounded_and_repeatable(self):
        import pefile
        from tools.hq_module_catalog import case_path
        game = Path(os.environ['NFSMW_HQ_PHASE_GAME'])
        canonical = case_path(game, '.nfsmw/runtime.exe')
        if not canonical.is_file():
            canonical = case_path(game, 'speed.exe')
        pe = pefile.PE(str(canonical))
        memory = pe.get_memory_mapped_image()[:pe.OPTIONAL_HEADER.SizeOfImage]
        memory += bytes(pe.OPTIONAL_HEADER.SizeOfImage - len(memory))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / 'baseline.bin'
            baseline.write_bytes(memory)
            digest = hashlib.sha256(memory).hexdigest()
            output = root / 'prepared'
            snapshots = phases.prepare_phases(game, baseline, output, baseline_sha256=digest)
            self.assertEqual([path.name for path in snapshots], ['callback.game.bin', 'render.game.bin'])
            callback, render = [path.read_bytes() for path in snapshots]
            base = 0x400000
            changed_callback = {i + base for i, (a, b) in enumerate(zip(memory[0x1000:0x48f2a5], callback[0x1000:0x48f2a5]), 0x1000) if a != b}
            self.assertEqual(changed_callback, set(range(0x5a30b2, 0x5a30b6)))
            changed_render = {i + base for i, (a, b) in enumerate(zip(callback[0x1000:0x48f2a5], render[0x1000:0x48f2a5]), 0x1000) if a != b}
            self.assertEqual(len(changed_render), 24)
            self.assertEqual({address for address in changed_render if not any(start <= address < start + size for start, size in phases.RENDER_RANGES)}, set())
            record = json.loads((output / phases.MARKER).read_text())
            self.assertNotIn(str(root), json.dumps(record))
            self.assertEqual(record['baseline_sha256'], digest)
            self.assertEqual([row['sha256'] for row in record['snapshots']], [hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshots])
            original = [p.read_bytes() for p in snapshots]
            phases.prepare_phases(game, baseline, output, baseline_sha256=digest)
            self.assertEqual(original, [p.read_bytes() for p in snapshots])
            restored_baseline = bytearray(memory)
            restore_at = 0x006de9f8 - base
            for offset in range(restore_at, restore_at + 8):
                restored_baseline[offset] ^= 0xff
            baseline.write_bytes(restored_baseline)
            restored_paths = phases.prepare_phases(game, baseline, root / 'restored',
                                                   baseline_sha256=hashlib.sha256(restored_baseline).hexdigest())
            self.assertEqual(restored_paths[0].read_bytes()[restore_at:restore_at + 8], bytes(restored_baseline[restore_at:restore_at + 8]))
            self.assertEqual(restored_paths[1].read_bytes()[restore_at:restore_at + 8], memory[restore_at:restore_at + 8])
            invalid_header = bytearray(memory);invalid_header[0] ^= 1
            baseline.write_bytes(invalid_header)
            with self.assertRaisesRegex(ValueError, 'headers'):
                phases.prepare_phases(game, baseline, output,
                                      baseline_sha256=hashlib.sha256(invalid_header).hexdigest())
            self.assertEqual(original, [p.read_bytes() for p in snapshots])
            baseline.write_bytes(memory[:-1])
            with self.assertRaises(ValueError):
                phases.prepare_phases(game, baseline, output, baseline_sha256=digest)
            self.assertEqual(original, [p.read_bytes() for p in snapshots])


if __name__ == '__main__':
    unittest.main()
