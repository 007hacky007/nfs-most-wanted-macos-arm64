"""Exercise the production Metal INTZ depth alias and sampling queue."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS Metal')
class INTZBackendTests(unittest.TestCase):
    def test_depth_alias_rendering_and_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'intz-backend'
            flags = ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if os.environ.get('NFSMW_INTZ_SANITIZE') == '1' else []
            result = subprocess.run(['clang', *flags, '-fobjc-arc', str(ROOT / 'tests/backend_intz_gpu.m'),
                '-I' + str(ROOT / 'runtime'), str(ROOT / 'runtime/vsemu.c'),
                '-Wl,-undefined,dynamic_lookup', '-framework', 'Foundation', '-framework', 'Metal',
                '-framework', 'AppKit', '-framework', 'QuartzCore', '-framework', 'GameController',
                '-framework', 'IOKit', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for mode in ('single', 'msaa'):
                with self.subTest(mode=mode):
                    result = subprocess.run([str(binary), mode], capture_output=True, text=True, timeout=30)
                    if result.returncode == 77:
                        self.skipTest('Metal device or sample count unavailable')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('deferred lifetime passed', result.stdout)

if __name__ == '__main__':
    unittest.main()
