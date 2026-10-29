"""D3D9 query contracts and actual offscreen Metal visibility counts."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires the native macOS backend')
class OcclusionQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        cls.com = cls.directory / 'query-com'
        cls.gpu = cls.directory / 'query-gpu'
        common = ['-I' + str(ROOT / 'runtime'), str(ROOT / 'runtime/vsemu.c'),
                  '-Wl,-undefined,dynamic_lookup']
        subprocess.run(['clang', str(ROOT / 'tests/backend_query_com.c'), *common,
                        '-o', str(cls.com)], check=True, capture_output=True)
        subprocess.run(['clang', '-fobjc-arc', str(ROOT / 'tests/backend_query_gpu.m'),
                        *common, '-framework', 'Foundation', '-framework', 'Metal',
                        '-framework', 'AppKit', '-framework', 'QuartzCore',
                        '-framework', 'GameController', '-framework', 'IOKit',
                        '-o', str(cls.gpu)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_com_metadata_flags_output_and_lifetime(self):
        result = subprocess.run([str(self.com)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_gpu_counts_pending_generation_lifetime_and_scheduling(self):
        result = subprocess.run([str(self.gpu)], capture_output=True, text=True, timeout=20)
        if result.returncode == 77:
            self.skipTest('Metal device unavailable inside this sandbox')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('hidden0, visible64/draw, nested128', result.stdout)


if __name__ == '__main__':
    unittest.main()
