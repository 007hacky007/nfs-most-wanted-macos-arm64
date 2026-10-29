"""Run ordered texture readback through the production queue encoder."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS backend')
class ReadbackBackend(unittest.TestCase):
    def test_ordered_readback_and_frame_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'readback-backend'
            flags = []
            if os.environ.get('NFSMW_READBACK_SANITIZE') == '1':
                flags = ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            result = subprocess.run(['clang', *flags, '-fobjc-arc', str(ROOT / 'tests/backend_readback_gpu.m'),
                '-I' + str(ROOT / 'runtime'), str(ROOT / 'runtime/vsemu.c'),
                '-Wl,-undefined,dynamic_lookup', '-framework', 'Foundation', '-framework', 'Metal',
                '-framework', 'AppKit', '-framework', 'QuartzCore', '-framework', 'GameController',
                '-framework', 'IOKit', '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for mode in ('single', 'msaa'):
                with self.subTest(mode=mode):
                    result = subprocess.run([str(binary), mode], capture_output=True, text=True, timeout=30)
                    if result.returncode == 77:
                        self.skipTest('Metal device unavailable inside this sandbox')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('one Present passed', result.stdout)

if __name__ == '__main__':
    unittest.main()
