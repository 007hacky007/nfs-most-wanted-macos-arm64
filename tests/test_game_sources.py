"""Source staging uses only pinned files and never modifies supplied copies."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import shutil
import subprocess
import sys
import warnings
import struct
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tests.test_install import raw_image, record
from tools.game_sources import stage_game


def pin(data):
    return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in entries:
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data)
    return stream.getvalue()


def iso_bytes(files):
    """A single ISO directory is enough to exercise real disc_files/RawISO."""
    image = bytearray(22 * 2048)
    for sector, kind in ((16, 1), (17, 255)):
        image[sector * 2048:sector * 2048 + 7] = bytes([kind]) + b'CD001\x01'
    root = record(b'\0', 20, 2048, True)
    image[16 * 2048 + 156:16 * 2048 + 156 + len(root)] = root
    directory = bytearray()
    for name, data in files.items():
        sector = len(image) // 2048
        directory += record((name + ';1').encode('ascii'), sector, len(data))
        image += data + bytes(-len(data) % 2048)
    assert len(directory) <= 2048
    image[20 * 2048:20 * 2048 + len(directory)] = directory
    return image


class GameSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = {'GLOBAL/One.bin': b'one', 'CARS/Two.bin': b'two',
                        'TRACKS/Three.bin': b'three', 'SOUND/Four.bin': b'four',
                        'speed.exe': b'unpatched', 'server.dll': b'server',
                        'server.cfg': b'config', 'bin.dat': b'disc0', 'd3dx9_26.dll': b'd3dx'}
        self.profile = {'schema_version': 1, 'profile': 'synthetic', 'archives': [], 'files': [],
                        'd3dx_cab': {'role': 0, 'path': 'd3dx.cab', **pin(b'cab')}}
        for role, (name, data) in enumerate(list(self.payload.items())[:4]):
            archive = zip_bytes([(name.replace('/', '\\'), data)])
            self.profile['archives'].append({'role': role, 'path': f'{role}compressed.zip', **pin(archive)})
            self.profile['files'].append({'path': name, 'required': True,
                                         'variants': [{'kind': 'source', **pin(data)}],
                                         'source': {'role': role, 'archive': f'{role}compressed.zip'}})
        for name, data in list(self.payload.items())[4:]:
            self.profile['files'].append({'path': name, 'required': name == 'speed.exe',
                                         'variants': [{'kind': 'source', **pin(data)}],
                                         'source': {'role': 0, 'disc_path': name}})
        self.profile['files'][4]['variants'] += [{'kind': 'official-1.3', **pin(b'patched')},
                                                {'kind': 'canonical', **pin(b'canonical')}]

    def destination(self, name='stage'):
        destination = self.root / name
        destination.mkdir()
        return destination

    def folder(self):
        source = self.root / 'folder'
        source.mkdir()
        for name, data in self.payload.items():
            target = source / name.lower()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (source / 'scripts').mkdir()
        (source / 'scripts/mod.asi').write_bytes(b'not copied')
        return source

    def discs(self, overrides=None, raw=False):
        images = []
        for role in range(4):
            row = self.profile['files'][role]
            entries = [(row['path'].replace('/', '\\'), self.payload[row['path']])]
            archive = (overrides or {}).get(role, zip_bytes(entries))
            files = {f'{role}compressed.zip': archive}
            if role == 0:
                files.update({name: data for name, data in list(self.payload.items())[4:-1]})
                files['d3dx.cab'] = b'cab'
            image = self.root / f'unnamed-{3-role}.bin'
            logical = iso_bytes(files)
            if raw:
                raw_image(image, logical)
            else:
                image.write_bytes(logical)
            images.append(image)
        return images

    def stage_discs(self, sources, destination):
        # Only the external cabinet decoder is substituted; ISO and ZIP handling are real.
        import subprocess
        with patch('tools.game_sources.subprocess.run', return_value=subprocess.CompletedProcess(
                ['cabextract'], 0, b'd3dx', b'')):
            return stage_game(sources, destination, profile=self.profile)

    def test_folder_normalizes_expected_paths_and_ignores_mods(self):
        source = self.folder()
        (source / 'speed.exe').write_bytes(b'patched')
        destination = self.destination()
        manifest = stage_game([source], destination, profile=self.profile)
        self.assertEqual((destination / 'GLOBAL/One.bin').read_bytes(), b'one')
        self.assertEqual((destination / 'speed.exe').read_bytes(), b'patched')
        self.assertFalse((destination / 'scripts').exists())
        self.assertTrue((source / 'scripts/mod.asi').exists())
        self.assertEqual(len(manifest['files']), 9)
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertEqual(next(r['variant'] for r in manifest['files'] if r['path'] == 'speed.exe'), 'official-1.3')

    def test_optional_files_may_be_absent_but_required_and_modified_files_fail(self):
        source = self.folder()
        for name in ('server.dll', 'server.cfg', 'bin.dat', 'd3dx9_26.dll'):
            (source / name).unlink()
        stage_game([source], self.destination(), profile=self.profile)
        (source / 'server.dll').write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError, 'server.dll'):
            stage_game([source], self.destination('bad-optional'), profile=self.profile)
        (source / 'server.dll').unlink()
        (source / 'global/one.bin').unlink()
        with self.assertRaisesRegex(ValueError, 'One.bin'):
            stage_game([source], self.destination('missing'), profile=self.profile)

    def test_destination_and_source_symlinks_are_refused(self):
        source = self.folder()
        dest = self.destination()
        (dest / 'save').write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            stage_game([source], dest, profile=self.profile)
        self.assertEqual((dest / 'save').read_bytes(), b'keep')
        (source / 'speed.exe').unlink()
        (source / 'speed.exe').symlink_to(source / 'server.dll')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            stage_game([source], self.destination('links'), profile=self.profile)

    def test_unordered_iso_files_are_identified_by_archive_role(self):
        images = self.discs()
        destination = self.destination()
        manifest = self.stage_discs([images[2], images[0], images[3], images[1]], destination)
        self.assertEqual([r['role'] for r in manifest['archives']], [0, 1, 2, 3])
        self.assertEqual((destination / 'd3dx9_26.dll').read_bytes(), b'd3dx')
        self.assertEqual((destination / 'bin.dat').read_bytes(), b'disc0')
        self.assertEqual(len(manifest['files']), 9)

    def test_image_folder_deduplicates_cue_and_raw_bin(self):
        self.discs(raw=True)
        cue = self.root / 'same.cue'
        cue.write_text('FILE "unnamed-3.bin" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
        destination = self.root.parent / (self.root.name + '-stage')
        destination.mkdir()
        self.addCleanup(lambda: shutil.rmtree(destination))
        manifest = self.stage_discs([self.root], destination)
        self.assertEqual(len(manifest['archives']), 4)

    def test_duplicate_missing_roles_and_wrong_archive_pin_fail(self):
        images = self.discs()
        for inputs in (images[:3], images[:3] + [images[0]]):
            with self.subTest(inputs=len(inputs)), self.assertRaises(ValueError):
                self.stage_discs(inputs, self.destination('bad' + str(len(list(self.root.glob('bad*'))))))
        self.profile['archives'][2]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'archive|ZIP|checksum'):
            self.stage_discs(images, self.destination('hash'))

    def test_cue_rejects_unsupported_tracks_offsets_modes_and_escaping_references(self):
        images = self.discs()
        cases = [
            'FILE "../outside.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00',
            'FILE "unnamed-3.bin" BINARY\nTRACK 01 AUDIO\nINDEX 01 00:00:00',
            'FILE "unnamed-3.bin" BINARY\nTRACK 01 MODE1/2352\nINDEX 01 00:00:00',
            'FILE "unnamed-3.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:01',
            'FILE "unnamed-3.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\nTRACK 02 AUDIO',
            'FILE "unnamed-3.bin" BINARY\nFILE "unnamed-2.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00',
        ]
        for i, text in enumerate(cases):
            cue = self.root / f'bad-{i}.cue'
            cue.write_text(text)
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'CUE'):
                self.stage_discs([cue, *images[1:]], self.destination(f'cue-{i}'))

    def test_all_zip_names_are_preflighted_before_any_output(self):
        cases = [(('../escape', b'x'), 'unsafe'), (('C:/escape', b'x'), 'unsafe'),
                 (('/escape', b'x'), 'unsafe'), (('global/one.BIN', b'x'), 'collision'),
                 (('GLOBAL/One.bin/child', b'x'), 'collision'), (('CARS/Two.bin', b'two'), 'duplicate')]
        for i, (extra, reason) in enumerate(cases):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                data = zip_bytes([('CARS/Two.bin', b'two'), extra])
            self.profile['archives'][1].update(pin(data))
            images = self.discs({1: data})
            destination = self.destination(f'zip-{i}')
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, reason):
                self.stage_discs(images, destination)
            self.assertEqual(list(destination.iterdir()), [])

    def test_zip_symlink_crc_and_wrong_payload_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            entry = zipfile.ZipInfo('CARS/Two.bin')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, b'other')
        bad_crc = bytearray(zip_bytes([('CARS/Two.bin', b'two')]))
        bad_crc[30 + len('CARS/Two.bin')] ^= 1
        for i, data in enumerate((stream.getvalue(), bytes(bad_crc), zip_bytes([('CARS/Two.bin', b'bad')]))):
            self.profile['archives'][1].update(pin(data))
            images = self.discs({1: data})
            with self.subTest(case=i), self.assertRaises((ValueError, zipfile.BadZipFile)):
                self.stage_discs(images, self.destination(f'payload-{i}'))

    def test_explicit_zip_directories_are_normalized_without_extra_directories(self):
        data = zip_bytes([('cars/', b''), ('cars/two.bin', b'two')])
        self.profile['archives'][1].update(pin(data))
        images = self.discs({1: data})
        destination = self.destination()
        self.stage_discs(images, destination)
        self.assertEqual({p.name for p in destination.iterdir() if p.is_dir()},
                         {'CARS', 'GLOBAL', 'TRACKS', 'SOUND'})
        data = zip_bytes([('EXTRA/', b''), ('CARS/Two.bin', b'two')])
        self.profile['archives'][1].update(pin(data))
        with self.assertRaisesRegex(ValueError, 'directory'):
            self.stage_discs(self.discs({1: data}), self.destination('extra-dir'))

    def test_cue_2048_and_canonical_runtime_are_accepted_and_checked(self):
        images = self.discs()
        cue = self.root / 'first.cue'
        cue.write_text('FILE "unnamed-3.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 00 00:00:00\nINDEX 01 00:00:00\n')
        self.stage_discs([cue, *images[1:]], self.destination())
        source = self.folder()
        self.profile['files'].append({'path': '.nfsmw/runtime.exe', 'required': False,
                                     'source': {'folder_only': True},
                                     'variants': [{'kind': 'canonical', **pin(b'canonical')}]})
        (source / '.nfsmw').mkdir()
        (source / '.nfsmw/runtime.exe').write_bytes(b'canonical')
        (source / 'speed.exe').write_bytes(b'canonical')
        destination = self.destination('canonical')
        stage_game([source], destination, profile=self.profile)
        self.assertEqual((destination / '.nfsmw/runtime.exe').read_bytes(), b'canonical')
        (source / '.nfsmw/runtime.exe').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'runtime.exe'):
            stage_game([source], self.destination('bad-runtime'), profile=self.profile)

    def test_bad_or_missing_cabinet_and_decoder_output_are_rejected(self):
        import subprocess
        images = self.discs()
        self.profile['d3dx_cab']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.stage_discs(images, self.destination('bad-cab'))
        self.profile['d3dx_cab'].update(pin(b'cab'))
        self.profile['d3dx_cab']['path'] = 'missing.cab'
        with self.assertRaisesRegex(ValueError, 'cabinet'):
            self.stage_discs(images, self.destination('missing-cab'))
        self.profile['d3dx_cab']['path'] = 'd3dx.cab'
        for code, output in ((1, b''), (0, b'wrong-dll')):
            with self.subTest(code=code), patch('tools.game_sources.subprocess.run',
                    return_value=subprocess.CompletedProcess(['cabextract'], code, output, b'')):
                with self.assertRaises(ValueError):
                    stage_game(images, self.destination('decoder-' + str(code)), profile=self.profile)

    def test_duplicate_image_copy_and_symlink_cue_reference_are_refused(self):
        images = self.discs()
        duplicate = self.root / 'duplicate.iso'
        duplicate.write_bytes(images[0].read_bytes())
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.stage_discs([*images, duplicate], self.destination())
        link = self.root / 'linked.bin'
        link.symlink_to(images[0])
        cue = self.root / 'linked.cue'
        cue.write_text('FILE "linked.bin" BINARY\nTRACK 01 MODE1/2048\nINDEX 01 00:00:00\n')
        with self.assertRaisesRegex(ValueError, 'CUE symlink'):
            self.stage_discs([cue, *images[1:]], self.destination('symlink-cue'))

    def test_zip_nul_name_is_rejected_before_zipfile_can_truncate_it(self):
        data = zip_bytes([('CARS/Two.binXextra', b'two')])
        data = data.replace(b'CARS/Two.binXextra', b'CARS/Two.bin\0extra')
        self.profile['archives'][1].update(pin(data))
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.stage_discs(self.discs({1: data}), self.destination())

    def test_script_style_import_uses_the_same_stager(self):
        import subprocess
        result = subprocess.run([sys.executable, '-c',
                                 'import game_sources; assert callable(game_sources.stage_game)'],
                                cwd=Path(__file__).resolve().parents[1] / 'tools', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.environ.get('NFSMW_GAME_SOURCE_TEST'), 'set NFSMW_GAME_SOURCE_TEST for full source staging')
    def test_actual_supported_source(self):
        destination = self.destination()
        manifest = stage_game([Path(os.environ['NFSMW_GAME_SOURCE_TEST'])], destination)
        self.assertGreaterEqual(len(manifest['files']), 1407)


if __name__ == '__main__':
    unittest.main()
