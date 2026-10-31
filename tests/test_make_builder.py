"""NFSMW Builder.app bundles exactly the pipeline sources, never game or archive files."""
from contextlib import redirect_stderr
import io
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from tools import make_builder

ROOT = Path(__file__).resolve().parents[1]


class MakeBuilderTests(unittest.TestCase):
    def test_bundle_sources_cover_pipeline_and_exclude_private_dirs(self):
        names = {p.as_posix() for p in make_builder.build_sources(ROOT)}
        for required in ('build.sh', 'gen.sh', 'requirements.txt', 'LICENSE', 'tools/build_app.py',
                         'tools/builder_cli.py', 'tools/progress.py', 'tools/helpers.py', 'tools/game_checksums.json',
                         'tools/rtpatch_decode.rs', 'third_party/rtpatch/codec.rs', 'runtime/main.c'):
            self.assertIn(required, names)
        self.assertFalse(any(n.split('/')[0] in ('tests', 'docs', 'vendor', 'gen', 'out', 'work', 'builder', 'pack.sh')
                             for n in names))
        self.assertFalse(any('__pycache__' in n for n in names))
        make_builder.check_bundle([Path(n) for n in names], ROOT)

    def test_entries_match_swift_bundled_source_entries(self):
        swift = (ROOT / 'builder/Sources/BuilderCore/Workspace.swift').read_text()
        match = re.search(r'bundledSourceEntries\s*=\s*\[([^\]]*)\]', swift)
        declared = re.findall(r'"([^"]+)"', match.group(1))
        self.assertEqual(declared, [*make_builder.ENTRIES, 'helpers'])
        self.assertEqual({p.parts[0] for p in make_builder.build_sources(ROOT)}, set(make_builder.ENTRIES))

    def test_forbidden_files_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'tools').mkdir()
            (root / 'tools/x.DLL').write_bytes(b'MZ')
            (root / 'tools/big.json').write_bytes(b'x' * (3 * 1024 * 1024))
            (root / 'tools/ok.py').write_text('pass')
            with self.assertRaisesRegex(ValueError, 'x.DLL'):
                make_builder.check_bundle([Path('tools/ok.py'), Path('tools/x.DLL')], root)
            with self.assertRaisesRegex(ValueError, 'larger than 2 MB'):
                make_builder.check_bundle([Path('tools/big.json')], root)
            for suffix in ('.iso', '.Bin', '.cue', '.zip', '.lzc', '.BUN', '.cab', '.exe', '.asi', '.big'):
                with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                    make_builder.check_bundle([Path('game/file' + suffix)], root)

    def test_release_requires_helpers(self):
        with patch.object(make_builder, 'build_binary', side_effect=AssertionError('built')), \
                redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as exit:
            make_builder.main(['--version', '1.0', '--release'])
        self.assertNotEqual(exit.exception.code, 0)
        self.assertIn('--release needs --helpers', err.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            make_builder.main(['--version', '1.0'])

    def test_info_plist(self):
        info = make_builder.info_plist('1.2.0')
        self.assertEqual(info['CFBundleIdentifier'], 'local.nfsmw.builder')
        self.assertEqual((info['CFBundleExecutable'], info['CFBundleName']), ('NFSMWBuilder', 'NFSMW Builder'))
        self.assertEqual((info['LSMinimumSystemVersion'], info['CFBundleShortVersionString']), ('12.0', '1.2.0'))
        self.assertEqual((info['CFBundleInfoDictionaryVersion'], info['NSPrincipalClass']), ('6.0', 'NSApplication'))

    def test_minos_parser(self):
        out = 'Load command 9\n      cmd LC_BUILD_VERSION\n    platform 1\n       minos 12.0\n         sdk 15.0\n'
        self.assertEqual(make_builder.parse_minos(out), '12.0')
        with self.assertRaises(ValueError):
            make_builder.parse_minos('nothing here')


if __name__ == '__main__':
    unittest.main()
