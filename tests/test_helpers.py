"""Bundled helpers are refused when changed or built from another version of the tree."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import helpers, official_patch


class HelpersTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_helpers(self, **changes):
        manifest = {}
        for name, record in helpers.expected_sources().items():
            binary = self.root / name
            binary.write_bytes(b'binary ' + name.encode())
            manifest[name] = {'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), **record,
                              **changes.get(name, {})}
        (self.root / 'helpers.json').write_text(json.dumps(manifest))

    def test_load_rejects_changed_binary_and_stale_source(self):
        self.write_helpers()
        loaded = helpers.load(self.root)
        self.assertEqual(set(loaded), {'innoextract', 'rtpatch-decode'})
        self.assertEqual(loaded['innoextract'], (self.root / 'innoextract').resolve())
        (self.root / 'innoextract').write_bytes(b'Binary innoextract')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            helpers.load(self.root)
        self.write_helpers(**{'rtpatch-decode': {'source_sha256': '0' * 64}})
        with self.assertRaisesRegex(ValueError, 'do not match'):
            helpers.load(self.root)
        self.write_helpers(innoextract={'patch_sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'do not match'):
            helpers.load(self.root)
        (self.root / 'helpers.json').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            helpers.load(self.root)

    def test_load_refuses_missing_or_symlinked_binary(self):
        self.write_helpers()
        (self.root / 'rtpatch-decode').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            helpers.load(self.root)
        (self.root / 'rtpatch-decode').symlink_to(self.root / 'innoextract')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            helpers.load(self.root)

    def test_official_patch_with_decoder_never_needs_rustc(self):
        payload = b'MZ synthetic patch'
        decoded = b'decoded speed.exe'
        archive = self.root / 'patch.exe'
        archive.write_bytes(payload)
        destination = self.root / 'game'
        destination.mkdir()
        (destination / 'speed.exe').write_bytes(b'old')
        decoder = self.root / 'decoder'
        decoder.write_text('#!/bin/sh\nprintf "decoded speed.exe" > "$7"\n')
        decoder.chmod(0o755)
        record = ('speed.exe', 0, 1, len(decoded), 0, 0, hashlib.sha256(decoded).hexdigest())
        with patch.object(official_patch, 'PATCH_EXE_SIZE', len(payload)), \
                patch.object(official_patch, 'PATCH_EXE_SHA', hashlib.sha256(payload).hexdigest()), \
                patch.object(official_patch, 'RECORDS', (record,)), \
                patch.object(official_patch.shutil, 'which', return_value=None) as which:
            manifest = official_patch.apply_official_patch(archive, destination, decoder=decoder)
            self.assertFalse(which.called)
            with self.assertRaisesRegex(RuntimeError, 'rustc'):
                official_patch.apply_official_patch(archive, destination)
        self.assertEqual(manifest, {'speed.exe': {'size': len(decoded), 'sha256': record[-1]}})
        self.assertEqual((destination / 'speed.exe').read_bytes(), decoded)


if __name__ == '__main__':
    unittest.main()
