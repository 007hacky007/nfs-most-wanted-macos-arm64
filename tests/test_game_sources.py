"""Source staging uses only pinned files and never modifies supplied copies."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
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
from tools import game_sources
from tools.game_sources import REQUIRED_RELEASE, accepted_copies, check_sources, describe, stage_game


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
        (source / 'scripts/mod.asi').write_bytes(b'mod')
        return source

    def discs(self, overrides=None, raw=False, extras=None):
        images = []
        for role in range(4):
            row = self.profile['files'][role]
            entries = [(row['path'].replace('/', '\\'), self.payload[row['path']])]
            archive = (overrides or {}).get(role, zip_bytes(entries))
            files = {f'{role}compressed.zip': archive}
            if role == 0:
                files.update({name: data for name, data in list(self.payload.items())[4:-1]})
                files['d3dx.cab'] = b'cab'
            files.update((extras or {}).get(role, {}))
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
        with patch('tools.game_sources.extract_cab_member', return_value=b'd3dx'):
            return stage_game(sources, destination, profile=self.profile)

    def test_folder_normalizes_expected_paths_and_keeps_the_rest_of_the_copy(self):
        source = self.folder()
        (source / 'speed.exe').write_bytes(b'patched')
        (source / 'global/readme.txt').write_bytes(b'windows extra')
        (source / '.DS_Store').write_bytes(b'finder')
        destination = self.destination()
        manifest = stage_game([source], destination, profile=self.profile)
        self.assertEqual((destination / 'GLOBAL/One.bin').read_bytes(), b'one')
        self.assertEqual((destination / 'speed.exe').read_bytes(), b'patched')
        # The whole copy goes in: mods and other Windows-only extras too, under the usual names.
        self.assertEqual((destination / 'scripts/mod.asi').read_bytes(), b'mod')
        self.assertIn('readme.txt', os.listdir(destination / 'GLOBAL'))
        self.assertFalse((destination / '.DS_Store').exists())
        self.assertTrue((source / 'scripts/mod.asi').exists())
        self.assertEqual(len(manifest['files']), 9)
        self.assertEqual(manifest['extras'], game_sources._inventory(
            [('scripts/mod.asi', source / 'scripts/mod.asi'), ('GLOBAL/readme.txt', source / 'global/readme.txt')]))
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
        for code, output in ((1, b''), (0, b''), (0, b'wrong-dll')):
            with self.subTest(code=code, output=output), patch('tools.install_game.subprocess.run',
                    return_value=subprocess.CompletedProcess(['tar'], code, output, b'')):
                with self.assertRaises(ValueError):
                    stage_game(images, self.destination(f'decoder-{code}-{len(output)}'), profile=self.profile)

    def test_extract_cab_member_uses_system_tar(self):
        import subprocess
        from tools.install_game import extract_cab_member
        with patch('tools.install_game.subprocess.run',
                   return_value=subprocess.CompletedProcess(['tar'], 0, b'dll', b'')) as run:
            self.assertEqual(extract_cab_member(Path('/x/a b.cab'), 'd3dx9_26.dll'), b'dll')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/tar', '-xOf', '/x/a b.cab', 'd3dx9_26.dll'])
        with patch('tools.install_game.subprocess.run',
                   return_value=subprocess.CompletedProcess(['tar'], 1, b'', b'bad')):
            with self.assertRaisesRegex(ValueError, 'could not decode the D3DX cabinet'):
                extract_cab_member(Path('/x/a.cab'), 'd3dx9_26.dll')

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

    def snapshot(self):
        return sorted((p.relative_to(self.root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in self.root.rglob('*'))

    def check(self, sources):
        return check_sources(sources, profile=self.profile)

    def stages(self, sources):
        destination = self.root.parent / (self.root.name + '-agree')
        shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir()
        self.addCleanup(lambda: shutil.rmtree(destination, ignore_errors=True))
        try:
            self.stage_discs(sources, destination)
        except (ValueError, zipfile.BadZipFile):
            return False
        return True

    def test_check_reports_all_problems_without_writing(self):
        source = self.folder()
        (source / 'cars/two.bin').write_bytes(b'TWO')
        (source / 'tracks/three.bin').write_bytes(b'changed')
        (source / 'sound/four.bin').unlink()
        for path in sorted(source.rglob('*'), reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        source.chmod(0o555)
        self.addCleanup(lambda: [p.chmod(0o755) for p in [source, *source.rglob('*')] if p.is_dir()])
        before, temporary = self.snapshot(), set(Path(tempfile.gettempdir()).iterdir())
        report = self.check([source])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({p for p in set(Path(tempfile.gettempdir()).iterdir()) - temporary
                          if p.name.startswith(('nfsmw', '.nfsmw'))}, set())
        self.assertFalse(report['ok'])
        self.assertEqual((report['kind'], report['checked'], report['failed']), ('folder', 5, 3))
        self.assertEqual({p['path'] for p in report['problems']},
                         {'CARS/Two.bin', 'TRACKS/Three.bin', 'SOUND/Four.bin'})
        missing = next(p for p in report['problems'] if p['path'] == 'SOUND/Four.bin')
        self.assertEqual(missing['found'], 'missing')
        self.assertEqual(missing['accepted'], [{'kind': 'source', **pin(b'four')}])
        changed = next(p for p in report['problems'] if p['path'] == 'CARS/Two.bin')
        self.assertEqual(changed['found'], pin(b'TWO'))
        message = describe(report)
        self.assertEqual(message, report['message'])
        self.assertIn('USA English Black Edition', message)
        self.assertIn('3 of 5 files are missing or different, for example', message)

    def test_check_accepts_folder_and_names_its_version(self):
        source = self.folder()
        report = self.check([source])
        self.assertTrue(report['ok'], report)
        self.assertEqual((report['kind'], report['failed'], report['problems']), ('folder', 0, []))
        self.assertIn('original discs', report['version'])
        (source / 'speed.exe').write_bytes(b'patched')
        self.assertEqual(self.check([source])['version'], 'USA English Black Edition, updated to 1.3')

    def test_check_and_stage_agree_on_every_fixture(self):
        images = self.discs()
        source = self.folder()
        cases = {'folder': [source], 'discs': images, 'shuffled': [images[2], images[0], images[3], images[1]],
                 'image folder': [self.root], 'three discs': images[:3],
                 'duplicate': images[:3] + [images[0]], 'one disc': images[:1]}
        for name, sources in cases.items():
            with self.subTest(name):
                self.assertEqual(self.check(sources)['ok'], self.stages(sources), name)
        (source / 'server.dll').write_bytes(b'unknown')
        (source / 'global/one.bin').unlink()
        self.assertEqual(self.check([source])['ok'], self.stages([source]))
        self.assertFalse(self.check([source])['ok'])
        self.profile['archives'][2]['sha256'] = '0' * 64
        self.assertEqual(self.check(images)['ok'], self.stages(images))
        self.profile['archives'][2].update(pin(zip_bytes([('TRACKS\\Three.bin', b'three')])))
        for extra in (('../escape', b'x'), ('global/one.BIN', b'x'), ('CARS/Two.bin', b'two')):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                data = zip_bytes([('CARS/Two.bin', b'two'), extra])
            self.profile['archives'][1].update(pin(data))
            changed = self.discs({1: data})
            with self.subTest(extra=extra):
                self.assertEqual(self.check(changed)['ok'], self.stages(changed))
                self.assertFalse(self.check(changed)['ok'])
        empty = self.root / 'empty'
        empty.mkdir()
        self.assertEqual(self.check([empty])['ok'], self.stages([empty]))

    def test_check_names_missing_disc_role(self):
        report = self.check(self.discs()[:3])
        self.assertFalse(report['ok'])
        self.assertEqual(report['kind'], 'discs')
        self.assertEqual(report['discs'], {'found': [0, 1, 2], 'missing': [3]})
        self.assertIn('Found 3 of the 4 discs. Disc 4 (the image that contains 3compressed.zip) is missing.',
                      describe(report))
        one = describe(self.check(self.discs()[:1]))
        self.assertIn('Found 1 of the 4 discs. Choose all four disc images together, or a folder that contains them.', one)

    def test_check_names_wrong_disc_and_empty_folder(self):
        images = self.discs()
        self.profile['archives'][1]['sha256'] = '0' * 64
        report = self.check(images)
        self.assertIn(images[1].name + ' is not one of the four supported discs: its 1compressed.zip '
                      'has a different size or checksum.', describe(report))
        empty = self.root / 'empty'
        empty.mkdir()
        report = self.check([empty])
        self.assertEqual(report['kind'], 'none')
        self.assertIn('This folder has no speed.exe and no disc images.', describe(report))
        self.assertIn('does not exist', describe(self.check([self.root / 'missing'])))

    def test_check_limits_detail_but_counts_all(self):
        source = self.folder()
        for index in range(30):
            self.profile['files'].append({'path': f'GLOBAL/Extra{index:02}.bin', 'required': True,
                                         'source': {'role': 0, 'archive': '0compressed.zip'},
                                         'variants': [{'kind': 'source', **pin(b'x')}]})
        report = self.check([source])
        self.assertEqual((len(report['problems']), report['failed']), (20, 30))
        self.assertIn('30 of 35 files', describe(report))

    def test_accepted_copies_match_profile(self):
        accepted = accepted_copies()
        self.assertEqual(accepted['release'], REQUIRED_RELEASE)
        self.assertEqual(accepted['folder']['required_files'], 1407)
        self.assertEqual(accepted['folder']['total_original'], 3028017159)
        self.assertEqual(accepted['folder']['total_official'], 3028022871)
        self.assertEqual(accepted['discs_total'], 2245282662)
        self.assertEqual([d['disc'] for d in accepted['discs']], [1, 2, 3, 4])
        self.assertEqual(accepted['discs'][0], {'disc': 1, 'archive': '0compressed.zip', 'size': 612595273,
                                                'sha256': 'd3a3179f4b794bab7cf633b1313b597d40934bb17a83d3e02b91af368624ee99'})
        self.assertEqual([(e['kind'], e['size']) for e in accepted['folder']['executables']],
                         [('source', 7250800), ('official-1.3', 7254894)])
        self.assertIn('Most Wanted (2012)', accepted['not_supported'])

    def app(self, name='NFSMW.app', bundle='local.nfsmw.native', record=True):
        """An NFSMW.app as the build leaves it: the installed tree, patched, with the extras of
        the copy (scripts/mod.asi) and derived files, and the extras recorded."""
        source = self.folder()
        (source / 'speed.exe').write_bytes(b'patched')
        for name_, data in (('.nfsmw/full/speed.exe', b'hq'), ('.nfsmw/runtime.exe', b'runtime'),
                            ('scripts/NFSMostWanted.WidescreenFix.ini', b'[MAIN]\n')):
            (source / name_).parent.mkdir(parents=True, exist_ok=True)
            (source / name_).write_bytes(data)
        extras = game_sources._inventory([('scripts/mod.asi', source / 'scripts/mod.asi')])
        (source / 'install-manifest.json').write_text(json.dumps({'source': {'extras': extras}} if record else {}))
        app = self.root / name
        (app / 'Contents/Resources').mkdir(parents=True)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': bundle,
                                                                  'NFSBuilderVersion': '0.3.6'}))
        source.rename(app / 'Contents/Resources/game')
        return app

    def read_only(self, root):
        for path in sorted([root, *root.rglob('*')], reverse=True):
            path.chmod(0o555 if path.is_dir() else 0o444)
        self.addCleanup(lambda: [p.chmod(0o755) for p in [root, *root.rglob('*')] if p.is_dir()])

    def test_app_built_earlier_is_checked_and_staged_like_its_game_folder(self):
        app = self.app()
        self.read_only(app)
        before = self.snapshot()
        report = self.check([app])
        self.assertTrue(report['ok'], report)
        self.assertEqual((report['kind'], report['app'], report['checked']), ('app', 'NFSMW.app', 5))
        self.assertEqual(report['version'], 'USA English Black Edition, updated to 1.3')
        destination = self.destination()
        manifest = stage_game([app], destination, profile=self.profile)
        self.assertEqual(manifest['source_kind'], 'folder')
        self.assertEqual((destination / 'speed.exe').read_bytes(), b'patched')
        # Everything an older build derived is left behind and built again; the extras stay.
        for derived in ('.nfsmw', 'scripts/NFSMostWanted.WidescreenFix.ini', 'install-manifest.json'):
            self.assertFalse((destination / derived).exists())
        self.assertEqual((destination / 'scripts/mod.asi').read_bytes(), b'mod')
        (destination / 'GLOBAL/One.bin').write_bytes(b'changed in the new build')
        self.assertEqual((app / 'Contents/Resources/game/global/one.bin').read_bytes(), b'one')
        self.assertEqual([entry for entry in self.snapshot() if entry[0].startswith('NFSMW.app')],
                         [entry for entry in before if entry[0].startswith('NFSMW.app')])

    def test_modified_or_missing_game_in_app_asks_for_the_original_copy(self):
        app = self.app()
        (app / 'Contents/Resources/game/cars/two.bin').write_bytes(b'modded')
        report = self.check([app])
        self.assertFalse(report['ok'])
        self.assertEqual(report['kind'], 'app')
        self.assertEqual(report['message'], 'The game inside NFSMW.app is missing or modified, so it cannot be '
                                            'reused. Choose your original game copy.')
        self.assertEqual([problem['path'] for problem in report['problems']], ['CARS/Two.bin'])
        with self.assertRaisesRegex(ValueError, 'CARS/Two.bin'):
            stage_game([app], self.destination(), profile=self.profile)
        shutil.rmtree(app / 'Contents/Resources/game')
        report = self.check([app])
        self.assertEqual((report['ok'], report['kind']), (False, 'app'))
        self.assertIn('missing or modified', report['message'])
        (app / 'Contents/Resources/game').mkdir()
        self.assertIn('missing or modified', self.check([app])['message'])

    def test_no_file_of_the_copy_in_an_app_is_ignored(self):
        """A missing or changed extra is found like a game file, and an app from an older Builder,
        which left the extras out, is not reused."""
        for change in ('missing', 'changed'):
            with self.subTest(change):
                app = self.app()
                extra = app / 'Contents/Resources/game/scripts/mod.asi'
                extra.unlink() if change == 'missing' else extra.write_bytes(b'changed')
                report = self.check([app])
                self.assertEqual((report['ok'], report['kind']), (False, 'app'))
                self.assertIn('missing or modified', report['message'])
                with self.assertRaisesRegex(ValueError, 'missing or modified'):
                    stage_game([app], self.destination(f'stage-{change}'), profile=self.profile)
                shutil.rmtree(app)
        app = self.app(record=False)
        report = self.check([app])
        self.assertEqual((report['ok'], report['kind']), (False, 'app'))
        self.assertEqual(report['message'], 'NFSMW.app was built by an older NFSMW Builder, which left part of '
                                            'your game copy out of it. Choose your original game copy once to '
                                            'build the complete app.')
        with self.assertRaisesRegex(ValueError, 'older NFSMW Builder'):
            stage_game([app], self.destination('stage-old'), profile=self.profile)

    def test_no_macos_code_from_the_copy(self):
        """A downloaded copy may hide a Mac program: it never goes into the game, and the files
        cloned from the copy keep the download's quarantine."""
        source = self.folder()
        shutil.copy('/usr/bin/true', source / 'readme.txt')                # a Mach-O under another name
        (source / 'Tool.app/Contents/MacOS').mkdir(parents=True)
        shutil.copy('/usr/bin/true', source / 'Tool.app/Contents/MacOS/Tool')
        (source / 'scripts/run.command').write_text('#!/bin/sh\n')
        (source / 'global/readme.dat').write_text('#!/bin/sh\necho hidden\n')   # a script with a game name
        (source / 'Helper/Contents/Resources').mkdir(parents=True)          # a bundle without an extension
        (source / 'Helper/Contents/Info.plist').write_text('<plist/>')
        (source / 'Helper/Contents/Resources/data.bin').write_text('data')
        (source / 'scripts/tool.jar').write_text('PK')
        (source / 'scripts/Open.TERMINAL').write_text('<plist/>')
        (source / 'scripts/mod.asi').chmod(0o755)
        mark = '0081;00000000;Test;'
        subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine', mark, str(source / 'scripts/mod.asi')],
                       check=True)
        destination = self.destination()
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            manifest = stage_game([source], destination, profile=self.profile)
        for name in ('readme.txt', 'Tool.app', 'scripts/run.command', 'GLOBAL/readme.dat', 'Helper',
                     'scripts/tool.jar', 'scripts/Open.TERMINAL'):
            self.assertFalse((destination / name).exists(), name)
            self.assertIn(f'left out of the app (macOS code): {name.replace("GLOBAL", "global")}\n',
                          log.getvalue())
        self.assertEqual(log.getvalue().count('Helper'), 1, 'a bundle is left out whole, named once')
        self.assertEqual(manifest['extras']['files'], 1)
        self.assertEqual(stat.S_IMODE((destination / 'scripts/mod.asi').stat().st_mode), 0o644)
        found = subprocess.run(['/usr/bin/xattr', '-p', 'com.apple.quarantine', str(destination / 'scripts/mod.asi')],
                               capture_output=True, text=True)
        self.assertEqual(found.stdout.strip(), mark)
        images = self.discs(extras={0: {'AutoRun.exe': b'MZ windows', 'Mac.dylib': b'library',
                                        'helper': Path('/usr/bin/true').read_bytes()[:4096],
                                        'readme.dat': b'#!/usr/bin/perl\n', 'tool.jar': b'PK'},
                                    # The same name on another disc: once, or beside the first disc's.
                                    1: {'AutoRun.exe': b'MZ windows', 'bin.dat': b'disc1'},
                                    2: {'AutoRun.exe': b'MZ other', 'bin.dat': b'disc0'}})
        destination = self.destination('discs')
        manifest = self.stage_discs(images, destination)
        self.assertEqual((destination / 'AutoRun.exe').read_bytes(), b'MZ windows')
        self.assertEqual((destination / 'd3dx.cab').read_bytes(), b'cab')
        self.assertEqual((destination / 'bin.dat').read_bytes(), b'disc0')
        self.assertEqual((destination / 'Disc 2/bin.dat').read_bytes(), b'disc1')
        self.assertEqual((destination / 'Disc 3/AutoRun.exe').read_bytes(), b'MZ other')
        self.assertFalse((destination / 'Disc 2/AutoRun.exe').exists())
        self.assertFalse((destination / 'Disc 3/bin.dat').exists())
        for name in ('Mac.dylib', 'helper', 'readme.dat', 'tool.jar', '0compressed.zip'):
            self.assertFalse((destination / name).exists(), name)
        self.assertEqual(manifest['extras']['files'], 4)  # AutoRun.exe, the cabinet and the two other copies

    def test_files_from_a_quarantined_disc_image_keep_its_quarantine(self):
        """Every file written from a downloaded image (ZIP members, disc root files, the D3DX
        library, the extras) gets the image's own quarantine; an image without one gives none."""
        images = self.discs(extras={0: {'AutoRun.exe': b'MZ windows'}})
        marks = {}
        for role, image in enumerate(images[:3]):
            marks[role] = f'0081;0000000{role};Test{role};'
            subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine', marks[role], str(image)], check=True)
        destination = self.destination()
        self.stage_discs(images, destination)
        expected = {'GLOBAL/One.bin': marks[0], 'CARS/Two.bin': marks[1], 'TRACKS/Three.bin': marks[2],
                    'SOUND/Four.bin': None, 'speed.exe': marks[0], 'server.dll': marks[0],
                    'd3dx9_26.dll': marks[0], 'AutoRun.exe': marks[0], 'd3dx.cab': marks[0]}
        for name, mark in expected.items():
            value = game_sources.quarantine(destination / name)
            self.assertEqual(value.decode() if value else None, mark, name)

    def test_a_fallback_copy_keeps_the_exact_quarantine_or_fails(self):
        source = self.root / 'source.bin'
        source.write_bytes(b'original')
        source.chmod(0o755)
        mark = b'0081;00000000;Test;'
        game_sources.set_quarantine(source, mark)
        with patch.object(game_sources, '_CLONEFILE', None):
            game_sources._clone(source, self.root / 'copy.bin')
            self.assertEqual(game_sources.quarantine(self.root / 'copy.bin'), mark)
            self.assertEqual(stat.S_IMODE((self.root / 'copy.bin').stat().st_mode), 0o644)
            with patch.object(game_sources, '_SETXATTR', lambda *args: -1), \
                    self.assertRaisesRegex(OSError, 'cannot keep the quarantine'):
                game_sources._clone(source, self.root / 'lost.bin')

    def test_other_apps_are_not_game_copies(self):
        app = self.app('Other.app', bundle='com.example.other')
        report = self.check([app])
        self.assertFalse(report['ok'])
        self.assertIn('Other.app is not an NFSMW.app built by NFSMW Builder', report['message'])
        with self.assertRaisesRegex(ValueError, 'not an NFSMW.app'):
            stage_game([app], self.destination(), profile=self.profile)

    def test_staged_copy_never_writes_through_to_the_source(self):
        source = self.root / 'source.bin'
        source.write_bytes(b'original')
        for clone in (game_sources._CLONEFILE, None):
            with self.subTest(clone=clone is not None), patch.object(game_sources, '_CLONEFILE', clone):
                target = self.root / f'target-{clone is not None}.bin'
                game_sources._clone(source, target)
                self.assertEqual(target.read_bytes(), b'original')
                with target.open('r+b') as stream:
                    stream.write(b'CHANGED')
                self.assertEqual(source.read_bytes(), b'original')
        self.assertIsNotNone(game_sources._CLONEFILE if sys.platform == 'darwin' else True)

    @unittest.skipUnless(os.environ.get('NFSMW_GAME_SOURCE_TEST'), 'set NFSMW_GAME_SOURCE_TEST for full source checks')
    def test_actual_supported_source_check(self):
        report = check_sources([Path(os.environ['NFSMW_GAME_SOURCE_TEST'])])
        self.assertTrue(report['ok'], report['message'])

    @unittest.skipUnless(os.environ.get('NFSMW_GAME_SOURCE_TEST'), 'set NFSMW_GAME_SOURCE_TEST for full source staging')
    def test_actual_supported_source(self):
        destination = self.destination()
        manifest = stage_game([Path(os.environ['NFSMW_GAME_SOURCE_TEST'])], destination)
        self.assertGreaterEqual(len(manifest['files']), 1407)


if __name__ == '__main__':
    unittest.main()
