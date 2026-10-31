"""The shared installer publishes only complete, isolated game variants."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.install_game import install
from tests.test_hq_variants import fixture, runtime_patches


class InstallPipelineTests(unittest.TestCase):
    def run_pipeline(self, root, *, fail_patch=False):
        base,hq,hq_hash,originals=fixture(root)
        pe=(hq/'LOGIC/41/speed.exe').read_bytes()
        (base/'d3dx9_26.dll').write_bytes(pe)
        profile={'schema_version':1,'profile':'synthetic installer fixture',
                 'archives':[{'role':role,'path':f'{role}compressed.zip','size':0,
                              'sha256':'0'*64}for role in range(4)],'files':[]}
        for file in sorted(base.rglob('*')):
            if file.is_file():
                data=file.read_bytes()
                profile['files'].append({'path':file.relative_to(base).as_posix(),'required':True,
                    'source':{'role':0,'disc_path':file.relative_to(base).as_posix()},
                    'variants':[{'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'kind':'source'}]})
        checksums=root/'checksums.json';checksums.write_text(json.dumps(profile))
        (base/'userdata').mkdir();(base/'userdata/save').write_bytes(b'keep save')
        ws=root/'widescreen.zip'
        with zipfile.ZipFile(ws,'w')as zipped:
            zipped.writestr('scripts/NFSMostWanted.WidescreenFix.ini','[MAIN]\nFixHUD=1\n')
            zipped.writestr('scripts/NFSMostWanted.WidescreenFix.tpk',b'fixture texture pack')
        patches={'official-1.3':root/'official.exe','widescreen':ws,'mw-hq':root/'hq.zip'}
        destination=root/'installed'

        def decode(archive,staging,decoder=None):
            self.assertEqual(archive,patches['official-1.3'])
            (staging/'speed.exe').write_bytes(pe)
            if fail_patch:raise ValueError('fixture decoder failure')
            return {'speed.exe':{'size':len(pe),'sha256':hashlib.sha256(pe).hexdigest()}}

        with ExitStack()as stack:
            stack.enter_context(patch('tools.game_sources.CHECKSUMS',checksums))
            stack.enter_context(patch('tools.patch_sources.verify_patch',side_effect=lambda key,path:Path(path)))
            stack.enter_context(patch('tools.official_patch.apply_official_patch',side_effect=decode))
            stack.enter_context(patch('tools.install_game.D3DX_SHA',hq_hash))
            stack.enter_context(patch('tools.install_game.OFFICIAL_EXE_SHA',hq_hash))
            stack.enter_context(runtime_patches(hq_hash))
            if fail_patch:
                with self.assertRaisesRegex(ValueError,'fixture decoder failure'):
                    install([base],destination,patches=patches,hq_source=hq)
                self.assertFalse(destination.exists())
                self.assertFalse(list(root.glob('.nfsmw-install-*')))
            else:
                manifest=install([base],destination,patches=patches,hq_source=hq)
                self.assertEqual(manifest['source']['source_kind'],'folder')
                self.assertEqual((destination/'speed.exe').read_bytes(),pe)
                self.assertEqual((destination/'.nfsmw/visuals/CARS/BASE/GEOMETRY.BIN').read_bytes(),b'HQ model')
                self.assertTrue((destination/'.nfsmw/full/CARS/ADDED/GEOMETRY.BIN').is_file())
                self.assertFalse((destination/'userdata').exists())
                self.assertTrue((destination/'install-manifest.json').is_file())
                self.assertNotIn(str(root),json.dumps(manifest))
        for name,data in originals.items():self.assertEqual((base/name).read_bytes(),data)
        self.assertEqual((base/'userdata/save').read_bytes(),b'keep save')

    def test_verified_folder_and_explicit_patches_build_all_variants(self):
        with tempfile.TemporaryDirectory()as temporary:self.run_pipeline(Path(temporary))

    def test_failed_patch_keeps_inputs_and_does_not_publish_installation(self):
        with tempfile.TemporaryDirectory()as temporary:self.run_pipeline(Path(temporary),fail_patch=True)


if __name__=='__main__':unittest.main()
