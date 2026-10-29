"""Exercise Metal MRT queue snapshots and the production pass/pipeline helpers."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS backend')
class MRTBackend(unittest.TestCase):
    def test_ordered_mrt_outputs_and_clears(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'mrt-backend'
            result = subprocess.run(['clang', '-fobjc-arc', str(ROOT / 'tests/backend_mrt_gpu.m'),
                '-I' + str(ROOT / 'runtime'), str(ROOT / 'runtime/vsemu.c'),
                '-Wl,-undefined,dynamic_lookup', '-framework', 'Foundation', '-framework', 'Metal',
                '-framework', 'AppKit', '-framework', 'QuartzCore', '-framework', 'GameController',
                '-framework', 'IOKit', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            if result.returncode == 77:
                self.skipTest('Metal device unavailable inside this sandbox')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ordered clears passed', result.stdout)

if __name__ == '__main__':
    unittest.main()
