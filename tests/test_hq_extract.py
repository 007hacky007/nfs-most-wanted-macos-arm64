import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.extract_hq import extract_hq, normalize_payload, safe_relative
from tools.build_hq_extractor import build_extractor


class HQExtractionTests(unittest.TestCase):
    def test_paths_reject_traversal_and_windows_absolute_names(self):
        for name in ('../escape', 'C:\\escape', '\\absolute', '/absolute', 'a/../../b', 'a\0b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_relative(name)
        self.assertEqual(str(safe_relative('Redist\\dx\\file.cab')), 'Redist/dx/file.cab')

    def test_identical_duplicates_collapse_and_different_options_remain_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app, out = root / 'app', root / 'out'
            app.mkdir()
            for name, data in [('same.bin$0', b'same'), ('same.bin$1', b'same'),
                               ('music.mus$0', b'original'), ('music.mus$1', b'playlist'),
                               ('GLOBALA.BUN#lang\\en', b'english'), ('GLOBALA.BUN#lang\\ru', b'russian')]:
                (app / name).write_bytes(data)
            manifest = normalize_payload(app, out)
            self.assertEqual((out / 'same.bin').read_bytes(), b'same')
            self.assertFalse((out / 'music.mus').exists())
            self.assertEqual(manifest['variants']['music.mus'], ['music.mus$0', 'music.mus$1'])
            self.assertEqual((out / 'GLOBALA.BUN#lang-en').read_bytes(), b'english')
            self.assertEqual(set(manifest['variants']), {'music.mus', 'GLOBALA.BUN'})
            self.assertEqual(manifest['files']['same.bin']['sha256'], hashlib.sha256(b'same').hexdigest())

    def test_case_collision_without_variant_suffix_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'app'
            app.mkdir()
            (app / 'data.bin').write_bytes(b'one')
            (app / 'DATA.BIN$0').write_bytes(b'two')
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                normalize_payload(app, Path(temporary) / 'out')

    def test_payload_symlink_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / 'app'
            app.mkdir()
            (app / 'link').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                normalize_payload(app, Path(temporary) / 'out')

    def test_failed_extractor_does_not_publish_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, extractor, destination = root / 'hq.zip', root / 'extractor', root / 'destination'
            extractor.write_bytes(b'native tool fixture')
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('setup.exe', b'fixture')
            with patch('tools.extract_hq.INSTALLER_MEMBERS', {'setup.exe': 7}), \
                    patch('tools.extract_hq.INSTALLER_SHA256', hashlib.sha256(b'fixture').hexdigest()), \
                    patch('tools.extract_hq.subprocess.run', side_effect=subprocess.CalledProcessError(2, 'extractor')):
                with self.assertRaises(subprocess.CalledProcessError):
                    extract_hq(archive, destination, extractor)
            self.assertFalse(destination.exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['extractor', 'hq.zip'])

    def test_verified_payload_is_published_with_input_and_output_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, extractor, destination = root / 'hq.zip', root / 'extractor', root / 'destination'
            extractor.write_bytes(b'native tool fixture')
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('setup.exe', b'fixture')

            def native_tool(arguments, **kwargs):
                if '--extract' in arguments:
                    app = Path(arguments[arguments.index('--output-dir') + 1]) / 'app'
                    app.mkdir(parents=True)
                    (app / 'data.bin').write_bytes(b'verified data')
                else:
                    kwargs['stdout'].write('fixture metadata\n')

            with patch('tools.extract_hq.INSTALLER_MEMBERS', {'setup.exe': 7}), \
                    patch('tools.extract_hq.INSTALLER_SHA256', hashlib.sha256(b'fixture').hexdigest()), \
                    patch('tools.extract_hq.subprocess.run', side_effect=native_tool):
                manifest = extract_hq(archive, destination, extractor)
            self.assertEqual((destination / 'data.bin').read_bytes(), b'verified data')
            self.assertEqual(manifest['files']['data.bin']['sha256'], hashlib.sha256(b'verified data').hexdigest())
            self.assertEqual(manifest['inputs']['setup.exe']['sha256'], hashlib.sha256(b'fixture').hexdigest())
            self.assertTrue((destination / '.hq-manifest.json').is_file())
            self.assertTrue((destination / '.hq-setup-metadata.txt').is_file())

    def test_unsafe_unselected_zip_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, extractor = root / 'hq.zip', root / 'extractor'
            extractor.touch()
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('../Redist/escape', b'bad')
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                extract_hq(archive, root / 'destination', extractor)
            self.assertFalse((root / 'destination').exists())

    def test_existing_destination_is_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileExistsError):
                extract_hq(root / 'missing.zip', root, root / 'missing-extractor')

    def test_source_hash_checked_before_extracting_or_building(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.tar.gz'
            source.write_bytes(b'not the pinned source')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                build_extractor(source, root / 'output')
            self.assertFalse((root / 'output').exists())

    @unittest.skipUnless(os.environ.get('NFSMW_HQ_ARCHIVE') and os.environ.get('NFSMW_INNOEXTRACT'),
                         'set NFSMW_HQ_ARCHIVE and NFSMW_INNOEXTRACT for full native HQ extraction')
    def test_supplied_hq_archive_extracts_and_preserves_runtime_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'hq'
            manifest = extract_hq(Path(os.environ['NFSMW_HQ_ARCHIVE']), root,
                                  Path(os.environ['NFSMW_INNOEXTRACT']))
            self.assertEqual(manifest['files']['LOGIC/41/speed.exe']['sha256'],
                             '8393f3487e3e024d6c2196d8adcd3f5b1b38077a893d9161a6f9ac61d587fa19')
            self.assertTrue((root / 'scripts/NFSMWUnlimiter.asi').is_file())
            self.assertIn('SOUND/PFDATA/MW_Music.mus', manifest['variants'])


if __name__ == '__main__':
    unittest.main()
