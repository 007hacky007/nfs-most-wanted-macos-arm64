import unittest

class RuntimePreparationTests(unittest.TestCase):
    def test_known_boundaries_are_adapted_once_and_missing_boundary_is_refused(self):
        from tools.prepare_hq_runtime import adapt_sources
        def function(address,body='POP32(c->eip); return;'):
            return f'/* ===== sub_{address:08x}  (1 insns) ===== */\nvoid sub_{address:08x}(CPU *restrict c) {{\n{body}\n}}\n'
        sources={'shard_0000.c':'#include "cpu.h"\n'+''.join(function(a)for a in (0x1007e80,0x1007cb0,0x1013660,0x1007b10,0x1007b30,0x1016f10))+function(0x1016f30,'    /* 01016f53  mov ecx, dword ptr [ebp - 8] */\nPOP32(c->eip); return;')}
        changed=adapt_sources('x360',sources)
        text=changed['shard_0000.c'];self.assertNotIn('void sub_01007e80(',text)
        self.assertIn('void sub_01007cb0_body(',text);self.assertIn('hq_video_resolution(c->ebp-8,c->ebp-4);',text)
        self.assertEqual(sources['shard_0000.c'].count('hq_video_resolution'),0)
        with self.assertRaisesRegex(ValueError,'boundary'):adapt_sources('x360',changed)
        unlimiter={'shard.c':function(0x1809740)+function(0x180ad50,'    DISPATCH_TAIL(c, 0x756aadu);')}
        changed=adapt_sources('unlimiter',unlimiter)['shard.c']
        self.assertIn('sub_01809740_body(',changed);self.assertLess(changed.index('hq_plugin_checkpoint(c,1);'),changed.index('DISPATCH_TAIL'))
        self.assertIn('sub_01c04a50_body(',adapt_sources('extraoptions',{'shard.c':function(0x1c04a50)})['shard.c'])
        xenon=adapt_sources('xenon',{'shard.c':function(0x24030f0)+function(0x2404940)})['shard.c']
        self.assertNotIn('sub_024030f0(',xenon);self.assertIn('sub_02404940(',xenon)
        with self.assertRaisesRegex(ValueError,'boundary'):adapt_sources('unlimiter',{'shard.c':function(0x1809740)+function(0x180ad50)})

    def test_source_fingerprints_and_managed_output_are_required(self):
        from dataclasses import asdict
        import hashlib,json,tempfile
        from pathlib import Path
        from tools.hq_module_catalog import MODULES,render_c_catalog
        from tools.prepare_hq_runtime import prepare_runtime,verify_runtime,PREPARED,MARKER
        from tools.prepare_hq_modules import processor_hashes
        from tools.generation_manifest import tool_hashes
        from tools.prepare_hq_runtime import module_profile,generation_versions
        module=MODULES[0]
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);source=root/'prepared';folder=source/module.key;folder.mkdir(parents=True)
            (source/'catalog.inc').write_text(render_c_catalog((module,)))
            body='/* synthetic generated module */\n';(folder/'shard_0000.c').write_text(body)
            record={'key':module.key,'sha256':module.sha256,'module':asdict(module),
                    'processors':processor_hashes(),
                    'raw_generation':{'version':1,'tools':tool_hashes(),'versions':generation_versions(),
                        'options':module_profile(module),'hooks':[],'branches':[],
                        'auxiliary':{'RELOCS':'synthetic','SEEDS':'synthetic'}},
                    'artifacts':{'shard_0000.c':hashlib.sha256(body.encode()).hexdigest()}}
            (folder/PREPARED).write_text(json.dumps(record));output=root/'runtime'
            result=prepare_runtime(source,output,(module,))
            self.assertEqual(result['sources'],['d3dx/shard_0000.c'])
            self.assertEqual(verify_runtime(output,(module,)),result)
            stale=json.loads(json.dumps(result));prepared=json.loads(stale['modules'][0]['prepared_marker'])
            prepared['raw_generation']['options']['RETEIP']=False
            marker=json.dumps(prepared);stale['modules'][0]['prepared_marker']=marker
            stale['modules'][0]['prepared_marker_sha256']=hashlib.sha256(marker.encode()).hexdigest()
            (output/MARKER).write_text(json.dumps(stale))
            with self.assertRaisesRegex(ValueError,'preparation provenance'):verify_runtime(output,(module,))
            (output/MARKER).write_text(json.dumps(result))
            (output/'d3dx/shard_0000.c').write_text('tampered runtime')
            with self.assertRaisesRegex(ValueError,'artifact differs'):verify_runtime(output,(module,))
            (output/'d3dx/shard_0000.c').write_text(body)
            (output/'catalog.inc').write_text('changed catalog')
            with self.assertRaisesRegex(ValueError,'catalog differs'):verify_runtime(output,(module,))
            (output/'catalog.inc').write_text(render_c_catalog((module,)))
            for change in ('tool','profile'):
                stale=json.loads(json.dumps(record))
                if change=='tool':stale['raw_generation']['tools']['tools/lift.py']='obsolete'
                else:stale['raw_generation']['options']['RETEIP']=False
                (folder/PREPARED).write_text(json.dumps(stale))
                with self.assertRaisesRegex(ValueError,'preparation provenance'):
                    prepare_runtime(source,output,(module,))
            (folder/PREPARED).write_text(json.dumps(record))
            previous=(output/MARKER).read_bytes();(folder/'shard_0000.c').write_text('tampered')
            # Runtime sources carry their own complete, checked preparation record.
            self.assertEqual(verify_runtime(output,(module,)),result)
            with self.assertRaisesRegex(ValueError,'artifact differs'):prepare_runtime(source,output,(module,))
            self.assertEqual((output/MARKER).read_bytes(),previous)
            (folder/'shard_0000.c').write_text(body)
            from unittest.mock import patch
            from tools import prepare_hq_runtime
            adapter=Path(prepare_hq_runtime.__file__).resolve();read_bytes=Path.read_bytes;changed=False
            def changed_bytes(path):
                if path.resolve()==adapter and changed:return b'changed during preparation'
                return read_bytes(path)
            def adapt(key,sources):
                nonlocal changed
                changed=True
                return sources
            with patch.object(Path,'read_bytes',changed_bytes),patch.object(prepare_hq_runtime,'adapt_sources',adapt):
                with self.assertRaisesRegex(ValueError,'adapter changed'):
                    prepare_runtime(source,output,(module,))
            self.assertEqual((output/MARKER).read_bytes(),previous)
            unmanaged=root/'unmanaged';unmanaged.mkdir();(unmanaged/'keep').write_text('retained')
            with self.assertRaisesRegex(ValueError,'unmanaged'):prepare_runtime(source,unmanaged,(module,))
            self.assertEqual((unmanaged/'keep').read_text(),'retained')
            with self.assertRaisesRegex(ValueError,'overlap'):prepare_runtime(source,source/'child',(module,))

if __name__=='__main__':unittest.main()
