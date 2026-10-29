import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_native


class NativeBuildSourcesTests(unittest.TestCase):
    def test_prepared_audio_is_verified_before_replacing_generated_callbacks(self):
        from tools import prepare_audio_callbacks as audio
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);prepared=root/'audio';prepared.mkdir()
            runtime=root/'runtime.exe';runtime.write_bytes(b'local verified runtime')
            table=root/'fntab.c';table.write_text('native table')
            target=root/'dynamic/callbacks.c';target.parent.mkdir();target.write_text('previous')
            code=b'locally prepared callbacks';(prepared/'callbacks.c').write_bytes(code)
            sha=lambda data:hashlib.sha256(data).hexdigest()
            record={'kind':'native-audio-callbacks','version':1,'source':'callbacks.c',
                    'runtime_sha256':sha(runtime.read_bytes()),'native_table_sha256':sha(table.read_bytes()),
                    'processors':audio._processors(),'generation_profile':dict(audio.GENERATION_PROFILE),
                    'files':{'callbacks.c':sha(code)}}
            (prepared/'manifest.json').write_text(json.dumps(record))
            with patch('tools.runtime_image.STANDARD_RUNTIME_SHA256',sha(runtime.read_bytes())):
                build_native.install_audio_callbacks(prepared,runtime,table,target)
                self.assertEqual(target.read_bytes(),code)
                for corrupt in ('artifact','table','processor'):
                    (prepared/'callbacks.c').write_bytes(code)
                    table.write_text('native table')
                    record['processors']=audio._processors()
                    if corrupt=='artifact':(prepared/'callbacks.c').write_bytes(b'changed')
                    if corrupt=='table':table.write_text('stale native table')
                    if corrupt=='processor':record['processors']={}
                    (prepared/'manifest.json').write_text(json.dumps(record))
                    target.write_text('previous')
                    with self.assertRaises(ValueError):
                        build_native.install_audio_callbacks(prepared,runtime,table,target)
                    self.assertEqual(target.read_text(),'previous')

    def test_hq_selects_replacements_once_and_isolates_module_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def put(name, text=''):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            for name in ('gen/all/shard_0000.c', 'gen/all/fntab.c',
                         'gen/d3dx/shard_0000.c', 'gen/dynamic/callbacks.c',
                         'out/routes/shard_0000.c', 'out/routes/variants.c',
                         'out/routes/routes.c', 'out/routes/register.c',
                         'out/routes/native_names.c', 'out/routes/checkpoints.c',
                         'gen/hq-runtime/d3dx/shard_0000.c',
                         'gen/hq-runtime/x360/shard_0000.c'):
                put(name)
            put('out/routes/manifest.json', json.dumps({'replaced_shards': ['shard_0000.c']}))
            put('gen/hq-runtime/.hq-runtime.json', json.dumps({'sources': [
                'd3dx/shard_0000.c', 'x360/shard_0000.c']}))
            with patch('tools.build_native.Path.cwd', return_value=root):
                ordinary = build_native.generated_sources(root=root)
                hq = build_native.generated_sources(hq=True, routes=root/'out/routes', root=root)
            sources = [p.relative_to(root).as_posix() for p, _ in hq]
            self.assertNotIn('gen/all/shard_0000.c', sources)
            self.assertNotIn('gen/d3dx/shard_0000.c', sources)
            self.assertIn('out/routes/shard_0000.c', sources)
            self.assertIn('gen/all/fntab.c', sources)
            self.assertIn('gen/dynamic/callbacks.c', sources)
            objects = [(folder / (source.stem+'.o')).as_posix() for source, folder in hq]
            self.assertEqual(len(objects), len(set(objects)))
            self.assertTrue(all('obj-hq' in str(folder) for _, folder in hq))
            self.assertTrue(any('/gen/d3dx/' in str(source) for source, _ in ordinary))
            put('gen/hq-runtime/.hq-runtime.json', json.dumps({'sources':['../escape.c']}))
            with self.assertRaisesRegex(ValueError, 'module source'):
                build_native.generated_sources(hq=True, routes=root/'out/routes', root=root)

    def test_generated_include_changes_invalidate_cached_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('runtime/cpu.h', 'gen/all/decls.h', 'gen/hq-runtime/catalog.inc',
                         'gen/hq-runtime/x360/decls.h', 'out/routes/decls.h'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            before = build_native.header_inputs(root, True, root/'out/routes')
            (root/'gen/hq-runtime/catalog.inc').write_text('changed catalog')
            after = build_native.header_inputs(root, True, root/'out/routes')
            self.assertNotEqual(before, after)
            (root/'gen/hq-runtime/x360/decls.h').write_text('changed declaration')
            self.assertNotEqual(after, build_native.header_inputs(root, True, root/'out/routes'))


if __name__ == '__main__':
    unittest.main()
