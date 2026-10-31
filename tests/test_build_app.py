"""The public entry works before dependencies or game preparation are needed."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class BuildAppEntryTests(unittest.TestCase):
    def test_help_and_missing_source_work_from_another_directory(self):
        with tempfile.TemporaryDirectory()as temporary:
            result=subprocess.run([sys.executable,str(ROOT/'tools/build_app.py'),'--help'],
                cwd=temporary,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('ISO',result.stdout);self.assertIn('BIN/CUE',result.stdout)
            result=subprocess.run([sys.executable,str(ROOT/'tools/build_app.py'),'missing-source'],
                cwd=temporary,capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertIn('source does not exist',result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()),[])

    def test_source_arguments_resolve_before_changing_to_project_directory(self):
        from tools.build_app import resolve_sources
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'disc one.iso').write_bytes(b'fixture')
            self.assertEqual(resolve_sources(['disc one.iso'],root),[(root/'disc one.iso').resolve()])

    def test_source_symlinks_are_rejected_before_resolution(self):
        from tools.build_app import resolve_sources
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);(root/'disc.iso').write_bytes(b'fixture')
            (root/'linked.iso').symlink_to(root/'disc.iso')
            with self.assertRaisesRegex(ValueError,'symlink'):
                resolve_sources(['linked.iso'],root)


def events(text):
    return [json.loads(line[len('NFSMW-EVENT '):]) for line in text.splitlines() if line.startswith('NFSMW-EVENT ')]


class BuildEventTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(os.chdir, os.getcwd())  # main() changes to its project folder
        from tools import build_app
        self.build_app = build_app
        for target, value in (('ROOT', self.root),):
            patcher = patch.object(build_app, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, {'NFSMW_PROGRESS': '1'})
        environment.start()
        self.addCleanup(environment.stop)

    def run_entry(self, *arguments):
        return subprocess.run([sys.executable, str(ROOT / 'tools/build_app.py'), *arguments],
                              cwd=self.root, capture_output=True, text=True)

    def test_progress_mode_emits_error_event_for_missing_source(self):
        result = self.run_entry('--progress', '/nonexistent/game')
        self.assertEqual(result.returncode, 2)
        self.assertIn('source does not exist', events(result.stdout)[-1]['error'])
        self.assertIsNone(events(result.stdout)[-1]['log'])
        result = self.run_entry('--progress', '--no-such-flag')
        self.assertEqual(result.returncode, 2)
        self.assertIn('error', events(result.stdout)[-1])

    def test_without_progress_output_has_no_events(self):
        environment = dict(os.environ)
        environment.pop('NFSMW_PROGRESS', None)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/build_app.py'), '/nonexistent/game'],
                                cwd=self.root, capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(events(result.stdout + result.stderr), [])
        self.assertIn('Build failed: source does not exist', result.stderr)

    def test_check_runs_before_any_download(self):
        report = {'ok': False, 'message': 'This is not the supported game copy.', 'kind': 'none'}
        with patch('game_sources.check_sources', return_value=report), \
                patch('patch_sources.fetch_patch', side_effect=AssertionError('downloaded')), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'not the supported game copy') as failure:
                self.build_app.build([self.root], self.root / 'cache', self.root / 'helpers')
        self.assertEqual(failure.exception.report, report)

    def test_step_order_and_done_event(self):
        import progress
        def install(sources, game, *, patches, extractor, decoder):
            self.assertEqual((extractor, decoder), ('x', 'd'))
            self.assertEqual(set(patches), {'official-1.3', 'widescreen', 'mw-hq'})
            for ident in ('game', 'patches', 'hq', 'variants'):
                progress.step(ident, ident)
        def prepare(game, output):
            for ident in ('translate', 'audio', 'modules', 'bootstrap', 'runtime', 'runtime', 'final'):
                progress.step(ident, ident)
        def fetch(key, cache, progress=None):
            progress(5, 10)
            return cache / key
        output = io.StringIO()
        with patch('game_sources.check_sources', return_value={'ok': True, 'version': 'v'}), \
                patch('patch_sources.fetch_patch', side_effect=fetch) as fetched, \
                patch('helpers.load', return_value={'innoextract': 'x', 'rtpatch-decode': 'd'}), \
                patch('install_game.install', side_effect=install), \
                patch('prepare_public_hq.prepare_build', side_effect=prepare), \
                patch('package_app.package_app', side_effect=lambda binary, game, app: app), \
                redirect_stdout(output):
            self.build_app.build([self.root / 'game'], self.root / 'cache', self.root / 'helpers')
        self.assertEqual([call.args[0] for call in fetched.call_args_list], ['official-1.3', 'widescreen', 'mw-hq'])
        found = events(output.getvalue())
        steps = [e['step'] for e in found if 'step' in e]
        self.assertEqual(steps, ['check', 'downloads', 'tools', 'game', 'patches', 'hq', 'variants', 'translate',
                                 'audio', 'modules', 'bootstrap', 'runtime', 'runtime', 'final', 'package'])
        downloads = [e for e in found if 'download' in e]
        self.assertEqual(len({e['total'] for e in downloads}), 1)
        self.assertEqual([e['received'] for e in downloads], sorted(e['received'] for e in downloads))
        self.assertEqual(found[-1], {'done': str((self.root / 'out/NFSMW.app').resolve())})

    def test_error_event_carries_log_path(self):
        output = io.StringIO()
        message = 'preparation failed (1); inspect /tmp/x/final-build.log'
        with patch.object(self.build_app, 'resolve_sources', return_value=[self.root]), \
                patch.object(self.build_app, 'prerequisites'), patch.object(self.build_app, 'environment'), \
                patch.object(self.build_app, 'build', side_effect=ValueError(message)), redirect_stdout(output), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(self.build_app.main(['--progress', 'game']), 2)
        self.assertEqual(events(output.getvalue())[-1], {'error': message, 'log': '/tmp/x/final-build.log'})
        for error in (subprocess.CalledProcessError(1, ['clang']), KeyError('boom')):
            output = io.StringIO()
            with patch.object(self.build_app, 'resolve_sources', return_value=[self.root]), \
                    patch.object(self.build_app, 'prerequisites'), patch.object(self.build_app, 'environment'), \
                    patch.object(self.build_app, 'build', side_effect=error), redirect_stdout(output), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(self.build_app.main(['--progress', 'game']), 2)
            self.assertEqual(events(output.getvalue())[-1]['error'], self.build_app.STEP_FAILED)

    def test_game_rejection_event_carries_the_report(self):
        output = io.StringIO()
        report = {'ok': False, 'message': 'Found 3 of the 4 discs.'}
        with patch.object(self.build_app, 'resolve_sources', return_value=[self.root]), \
                patch.object(self.build_app, 'prerequisites'), patch.object(self.build_app, 'environment'), \
                patch.object(self.build_app, 'build', side_effect=self.build_app.GameCopyError(report)), \
                redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(self.build_app.main(['--progress', 'a']), 2)
        self.assertEqual(events(output.getvalue())[-1], {'error': 'Found 3 of the 4 discs.', 'report': report})

    def test_several_sources_with_spaces_stay_separate(self):
        from tools.build_app import resolve_sources
        names = ['Disc 1 (USA).iso', 'Disc "2".iso']
        for name in names:
            (self.root / name).write_bytes(b'x')
        self.assertEqual(resolve_sources(names, self.root), [(self.root / n).resolve() for n in names])

    def test_cache_directory_prefers_flag_then_environment(self):
        with patch.dict(os.environ, {'NFSMW_CACHE_DIR': str(self.root / 'env')}):
            self.assertEqual(self.build_app.cache_directory(str(self.root / 'flag')), (self.root / 'flag').resolve())
            self.assertEqual(self.build_app.cache_directory(), (self.root / 'env').resolve())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('NFSMW_CACHE_DIR', None)
            self.assertEqual(self.build_app.cache_directory(), self.root / 'out/downloads')

    def test_helpers_need_only_clang_codesign_and_tar(self):
        with patch.object(self.build_app.shutil, 'which', side_effect=lambda name: None if name in ('cmake', 'rustc')
                          else '/usr/bin/' + name):
            self.build_app.prerequisites(helpers=True)
            with self.assertRaisesRegex(ValueError, 'cmake, rustc'):
                self.build_app.prerequisites()


if __name__=='__main__':unittest.main()
