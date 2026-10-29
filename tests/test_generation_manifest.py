import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_hq_module_catalog import fixture_dll
from tools.lift import RawLifter


class GenerationManifestTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.generation_manifest'),
                             'generation provenance is not implemented')
        from tools import generation_manifest
        return generation_manifest

    def fixture(self, root):
        exe=root/'image.exe';exe.write_bytes(fixture_dll())
        generated=root/'generated';generated.mkdir()
        for name in ('shard_0000.c','stubs.c','decls.h','fntab.c'):
            (generated/name).write_text('/* synthetic fixture */\n')
        hooks=root/'hooks';hooks.write_text('0x401005,00401000,401005\n')
        branches=root/'branches';branches.write_text('00401010:00401020\n')
        return exe,generated,hooks,branches

    def test_record_verifies_normalized_inputs_and_contains_no_local_paths(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe,generated,hooks,branches=self.fixture(root)
            api.record_generation(generated,exe,hooks,branches)
            hooks.write_text('401000,401005');branches.write_text('0x401010:0x401020')
            result=api.verify_generation(generated,exe,hooks,branches)
            self.assertEqual(result['hooks'],[0x401000,0x401005])
            self.assertEqual(result['branches'],[[0x401010,0x401020]])
            serialized=(generated/'generation-manifest.json').read_text()
            self.assertNotIn(str(root),serialized)
            self.assertNotIn(str(Path.cwd()),serialized)

    def test_stale_inputs_and_exact_artifact_inventory_are_rejected(self):
        api=self.api()
        for change in ('exe','hooks','branches','shard','missing','extra','tool','missing_options'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                exe,generated,hooks,branches=self.fixture(Path(tmp))
                api.record_generation(generated,exe,hooks,branches)
                if change=='exe':exe.write_bytes(exe.read_bytes()+b'x')
                if change=='hooks':hooks.write_text('401001')
                if change=='branches':branches.write_text('401010:401021')
                if change=='shard':(generated/'shard_0000.c').write_text('changed')
                if change=='missing':(generated/'stubs.c').unlink()
                if change=='extra':(generated/'shard_0001.c').write_text('extra')
                if change=='tool':
                    manifest=generated/'generation-manifest.json';data=json.loads(manifest.read_text())
                    data['tools']['tools/lift.py']='0'*64;manifest.write_text(json.dumps(data))
                if change=='missing_options':
                    manifest=generated/'generation-manifest.json';data=json.loads(manifest.read_text())
                    del data['options'];manifest.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError,'generation'):
                    api.verify_generation(generated,exe,hooks,branches)

    def test_input_changes_during_generation_never_publish_a_manifest(self):
        api=self.api()
        for change in ('exe','relocs','options'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                exe,generated,hooks,branches=self.fixture(Path(tmp))
                relocs=Path(tmp)/'relocs';relocs.write_text('10001008\n')
                environment={'RELOCS':str(relocs),'X87PC':'1'}
                capture=api.capture_generation(exe,hooks=hooks.read_text(),
                    branches=branches.read_text(),environment=environment)
                if change=='exe':exe.write_bytes(exe.read_bytes()+b'x')
                if change=='relocs':relocs.write_text('10001009\n')
                if change=='options':environment['X87PC']='0'
                with self.assertRaisesRegex(ValueError,'generation'):
                    api.write_generation(generated,capture)
                self.assertFalse((generated/'generation-manifest.json').exists())

    def test_actual_generator_publishes_a_verified_manifest(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as tmp:
            exe,generated,hooks,branches=self.fixture(Path(tmp))
            hooks.write_text('');branches.write_text('')
            relocs=Path(tmp)/'relocs';relocs.write_text('')
            env=dict(os.environ)
            for key in ('HOOKS','BRANCH_HOOKS','INLINE_LIST','FLAGABI','OVERRIDE','SEEDS','CODE_RVA_START','LREGS'):
                env.pop(key,None)
            env.update(GENOUT=str(generated),RELOCS=str(relocs),X87PC='1')
            run=subprocess.run([sys.executable,'tools/genall.py',str(exe),'1'],env=env,
                               capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            result=api.verify_generation(generated,exe,hooks,branches)
            self.assertTrue(result['options']['X87PC'])
            self.assertNotIn('stubs.c',result['artifacts'])

    def test_out_of_text_conditional_branch_is_counted_as_a_trap(self):
        lifter=RawLifter(bytes.fromhex('0f84faef0f00c3'))
        code,_=lifter.lift(0x401000)
        self.assertIn('"branch-out"',code)
        self.assertEqual(lifter.traps,1)
        self.assertEqual(lifter.trap_kinds['branch-out'],1)


if __name__=='__main__':unittest.main()
