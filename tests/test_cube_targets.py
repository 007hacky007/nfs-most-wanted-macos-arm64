"""Actual cube COM face routing and six independent Metal face draws."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS backend')
class CubeTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.com = cls.directory / 'cube-com'
        cls.gpu = cls.directory / 'cube-gpu'
        cls.routes = cls.directory / 'targets.bin'
        common = ['-I' + str(ROOT / 'runtime'), str(ROOT / 'runtime/vsemu.c'), '-Wl,-undefined,dynamic_lookup']
        subprocess.run(['clang', str(ROOT / 'tests/backend_cube_com.c'), *common, '-o', str(cls.com)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_cube_vtable_surface_and_target(self):
        result = subprocess.run([str(self.com)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_six_gpu_faces_from_com_targets(self):
        subprocess.run([str(self.com), str(self.routes)], check=True, capture_output=True)
        subprocess.run(['clang', '-fobjc-arc', str(ROOT / 'tests/backend_cube_gpu.m'),
                        '-I' + str(ROOT / 'runtime'), str(ROOT / 'runtime/vsemu.c'),
                        '-Wl,-undefined,dynamic_lookup', '-framework', 'Foundation',
                        '-framework', 'Metal', '-framework', 'AppKit', '-framework', 'QuartzCore',
                        '-framework', 'GameController', '-framework', 'IOKit', '-o', str(self.gpu)],
                       check=True, capture_output=True)
        result = subprocess.run([str(self.gpu), str(self.routes)], capture_output=True, text=True, timeout=20)
        if result.returncode == 77:
            self.skipTest('Metal device unavailable inside this sandbox')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('six distinct GPU cube faces', result.stdout)

if __name__ == '__main__':
    unittest.main()
