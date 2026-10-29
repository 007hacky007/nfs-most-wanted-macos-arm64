import os
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.official_patch import apply_official_patch
from tools import official_patch


class OfficialPatchTests(unittest.TestCase):
    def test_direct_executable_and_zip_produce_the_same_verified_payload(self):
        payload=b'MZ original native-decoder test input'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);executable=root/'patch.exe';archive=root/'patch.zip'
            executable.write_bytes(payload)
            with zipfile.ZipFile(archive,'w') as zipped:
                zipped.writestr('nfsmwpatch1.3.exe',payload)
            with patch.object(official_patch,'PATCH_EXE_SIZE',len(payload)),patch.object(
                    official_patch,'PATCH_EXE_SHA',hashlib.sha256(payload).hexdigest()):
                self.assertEqual(official_patch.read_patch_payload(executable),payload)
                self.assertEqual(official_patch.read_patch_payload(archive),payload)
                executable.write_bytes(payload+b'x')
                with self.assertRaisesRegex(ValueError,'unsupported official patch'):
                    official_patch.read_patch_payload(executable)
                executable.write_bytes(bytes(len(payload)))
                with self.assertRaisesRegex(ValueError,'unsupported official patch'):
                    official_patch.read_patch_payload(executable)

    def test_modified_installer_does_not_change_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / 'game'
            destination.mkdir()
            (destination / 'speed.exe').write_bytes(b'original')
            archive = root / 'patch.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('nfsmwpatch1.3.exe', b'MZ' + bytes(12777354))
            with self.assertRaisesRegex(ValueError, 'unsupported official patch'):
                apply_official_patch(archive, destination)
            self.assertEqual((destination / 'speed.exe').read_bytes(), b'original')
            self.assertEqual(list(destination.iterdir()), [destination / 'speed.exe'])

    def test_archive_cannot_supply_output_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / 'game'
            destination.mkdir()
            archive = root / 'patch.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('../speed.exe', b'bad')
            with self.assertRaises(ValueError):
                apply_official_patch(archive, destination)
            self.assertEqual(list(destination.iterdir()), [])
            self.assertFalse((root / 'speed.exe').exists())

    @unittest.skipUnless(os.environ.get('NFSMW_PATCH_ARCHIVE'),
                         'set NFSMW_PATCH_ARCHIVE for the local official patch integration test')
    def test_known_patch_extracts_seven_verified_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            (destination / 'speed.exe').write_bytes(b'old version')
            (destination / 'keep.bin').write_bytes(b'untouched')
            manifest = apply_official_patch(Path(os.environ['NFSMW_PATCH_ARCHIVE']), destination)
            self.assertEqual(len(manifest), 7)
            self.assertEqual(manifest['speed.exe']['sha256'],
                             'e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb')
            self.assertEqual((destination / 'speed.exe').stat().st_size, 7254894)
            self.assertEqual((destination / 'GLOBAL/gameplay.bin').stat().st_size, 2105216)
            self.assertEqual((destination / 'keep.bin').read_bytes(), b'untouched')


if __name__ == '__main__':
    unittest.main()
