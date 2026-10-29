"""Compile synthetic shaders into the real normal and Enhanced Metal namespaces."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS Metal')
class ShaderNamespaceTests(unittest.TestCase):
    def test_shader_id_families_and_pipeline_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            for enhanced in (0, 1):
                with self.subTest(enhanced=enhanced):
                    binary = Path(temp) / ('namespace-' + str(enhanced))
                    result = subprocess.run(['clang', '-fobjc-arc', '-DNFS_ENHANCED=' + str(enhanced),
                        str(ROOT / 'tests/backend_shader_namespace_gpu.m'), '-I' + str(ROOT / 'runtime'),
                        str(ROOT / 'runtime/vsemu.c'), '-Wl,-undefined,dynamic_lookup',
                        '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'AppKit',
                        '-framework', 'QuartzCore', '-framework', 'GameController', '-framework', 'IOKit',
                        '-o', str(binary)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                    if result.returncode == 77:
                        self.skipTest('Metal device unavailable inside this sandbox')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('high PS/VS keys passed', result.stdout)

if __name__ == '__main__':
    unittest.main()
