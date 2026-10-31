"""builder_cli prints one NFSMW-EVENT result per command and never writes into game copies."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b'synthetic HQ package'


def events(text):
    return [json.loads(line[len('NFSMW-EVENT '):]) for line in text.splitlines() if line.startswith('NFSMW-EVENT ')]


class BuilderCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        from tools import builder_cli
        self.cli = builder_cli
        import patch_sources
        self.sources = patch_sources
        specs = {key: replace(spec, size=len(PAYLOAD) + index, sha256=hashlib.sha256(PAYLOAD + bytes(index)).hexdigest())
                 for index, (key, spec) in enumerate(patch_sources.SOURCES.items())}
        mapping = patch.dict(patch_sources.SOURCES, specs)
        mapping.start()
        self.addCleanup(mapping.stop)

    def payload(self, key):
        index = list(self.sources.SOURCES).index(key)
        return PAYLOAD + bytes(index)

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = self.cli.main(list(argv))
        return status, events(out.getvalue())

    def test_check_game_rejects_bad_copy_without_writing_or_fetching(self):
        game = self.root / 'My "Game" copy'
        game.mkdir()
        (game / 'notes.txt').write_text('keep')
        before = sorted((p.name, p.stat().st_mtime_ns) for p in game.iterdir())
        with patch.object(self.sources, 'fetch_patch', side_effect=AssertionError('network')):
            status, found = self.call('check-game', str(game))
        self.assertEqual(status, 1)
        self.assertIn('This folder has no speed.exe and no disc images.', found[-1]['error'])
        self.assertEqual(found[-1]['report']['kind'], 'none')
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in game.iterdir()), before)

    def test_check_game_accepts_supported_copy_and_passes_every_path(self):
        report = {'ok': True, 'version': 'USA English Black Edition, 4 CDs', 'kind': 'discs'}
        paths = [str(self.root / 'Disc 1 (USA).iso'), str(self.root / 'Disc "2".iso')]
        with patch('game_sources.check_sources', return_value=report) as check:
            status, found = self.call('check-game', *paths)
        self.assertEqual(status, 0)
        self.assertEqual(found, [{'game': 'ok', 'version': report['version'], 'kind': 'discs'}])
        self.assertEqual(check.call_args.args[0], [Path(p) for p in paths])

    def test_accepted_copies_event(self):
        status, found = self.call('accepted-copies')
        self.assertEqual(status, 0)
        self.assertEqual(found[0]['accepted']['folder']['required_files'], 1407)

    def test_downloads_status_missing_partial_ready(self):
        cache = self.root / 'cache'
        cache.mkdir()
        spec = self.sources.SOURCES
        (cache / spec['official-1.3'].filename).write_bytes(self.payload('official-1.3'))
        (cache / spec['widescreen'].filename).write_bytes(b'x' * spec['widescreen'].size)
        with patch.object(self.cli, 'SMALL_BYTES', 10 ** 9), patch.object(self.sources, 'RESUMABLE_BYTES', 4):
            (cache / ('.' + spec['mw-hq'].filename + '.partial')).write_bytes(b'abc')
            status, found = self.call('downloads', 'status', '--cache-dir', str(cache), '--helpers')
        self.assertEqual(status, 0)
        result = found[-1]
        self.assertEqual(result['downloads'], {'official-1.3': 'ready', 'widescreen': 'missing', 'mw-hq': 'partial'})
        self.assertEqual(result['partial_bytes'], {'mw-hq': 3})
        self.assertEqual(result['total_bytes'], sum(spec[k].size for k in ('official-1.3', 'widescreen', 'mw-hq')))
        self.assertEqual(result['remaining_bytes'], spec['widescreen'].size + spec['mw-hq'].size - 3)
        status, found = self.call('downloads', 'status', '--cache-dir', str(cache))
        self.assertIn('hq-extractor', found[-1]['downloads'])

    def test_import_rejects_wrong_file_and_keeps_source(self):
        source = self.root / 'Downloads' / 'MW_HQ_1.20.9 (1).zip'
        source.parent.mkdir()
        source.write_bytes(b'not it')
        cache = self.root / 'cache'
        status, found = self.call('downloads', 'import', 'mw-hq', str(source), '--cache-dir', str(cache))
        self.assertEqual(status, 1)
        self.assertEqual(found[-1], {'error': 'This is not MW_HQ_1.20.9.zip: its size or checksum is different.'})
        self.assertEqual(source.read_bytes(), b'not it')
        self.assertEqual(list(source.parent.iterdir()), [source])
        source.write_bytes(self.payload('mw-hq'))
        status, found = self.call('downloads', 'import', 'mw-hq', str(source), '--cache-dir', str(cache))
        self.assertEqual((status, found[-1]), (0, {'downloads': 'ready'}))
        self.assertEqual(list(source.parent.iterdir()), [source])

    def test_fetch_reports_bytes_then_ready(self):
        def fetch(key, cache, progress=None):
            progress(1, 2)
            return cache / key
        with patch.object(self.sources, 'fetch_patch', side_effect=fetch), \
                patch.dict(os.environ, {'NFSMW_PROGRESS': '1'}):
            status, found = self.call('downloads', 'fetch', '--cache-dir', str(self.root), '--helpers')
        self.assertEqual(status, 0)
        self.assertEqual([e['download'] for e in found[:-1]], ['official-1.3', 'widescreen', 'mw-hq'])
        self.assertEqual(found[-1], {'downloads': 'ready'})

    def test_unexpected_exception_becomes_error_event(self):
        with patch('game_sources.accepted_copies', side_effect=KeyError('x')):
            status, found = self.call('accepted-copies')
        self.assertEqual(status, 1)
        self.assertEqual(found, [{'error': self.cli.build_app.STEP_FAILED}])
        with patch.object(self.sources, 'fetch_patch', side_effect=self.sources.DownloadError('offline')):
            status, found = self.call('downloads', 'fetch', '--cache-dir', str(self.root))
        self.assertEqual((status, found[-1]), (1, {'error': self.cli.build_app.download_failed('official-1.3')}))

    def test_script_runs_from_another_directory(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/builder_cli.py'), 'accepted-copies'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events(result.stdout)[0]['accepted']['discs_total'], 2245282662)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/builder_cli.py'), 'nope'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', events(result.stdout)[0])


if __name__ == '__main__':
    unittest.main()
