"""The public entry works before dependencies or game preparation are needed."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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


if __name__=='__main__':unittest.main()
