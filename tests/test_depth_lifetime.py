"""A reset sweep cannot discard a concurrently published depth texture alias."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires native Objective-C runtime')
class DepthLifetimeTests(unittest.TestCase):
    def test_reset_sweep_preserves_new_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'depth-lifetime'
            flags = ['-fobjc-arc', '-O1', '-I' + str(ROOT / 'runtime'),
                     '-framework', 'Foundation', '-framework', 'Metal',
                     '-framework', 'AppKit', '-framework', 'QuartzCore',
                     '-framework', 'GameController', '-framework', 'IOKit',
                     '-Wl,-undefined,dynamic_lookup']
            if os.environ.get('NFSMW_DEPTH_LIFETIME_SANITIZE') == '1':
                flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            result = subprocess.run(['clang', *flags, str(ROOT / 'tests/backend_depth_lifetime.m'),
                                     '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('no Metal device or GPU work', result.stdout)


if __name__ == '__main__':
    unittest.main()
