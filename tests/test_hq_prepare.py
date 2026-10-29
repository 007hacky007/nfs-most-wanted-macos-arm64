"""Headless preparation boundaries use native CPU/SEH and keyboard semantics."""
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS runtime')
class PrepareTests(unittest.TestCase):
    def test_boundaries_restore_and_hotkey_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'prepare'
            flags = ['-O1', '-g', '-fno-strict-aliasing', '-Wno-deprecated-declarations',
                     '-I' + str(ROOT / 'runtime')]
            if os.environ.get('NFSMW_PREPARE_SANITIZE') == '1':
                flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
            result = subprocess.run(['clang', *flags, str(ROOT / 'tests/hq_prepare_native.c'),
                str(ROOT / 'runtime/keyboard.c'), str(ROOT / 'runtime/win_keyboard.c'),
                '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('HQ_PREPARE_BOUNDARIES_OK', result.stdout)
            fixture=Path(tmp)/'synthetic-global.lzc'
            def check(data, accepted):
                with fixture.open('wb') as stream:
                    stream.seek(0xfa9e50)
                    stream.write(data)
                result=subprocess.run([str(binary),str(fixture),str(int(accepted))],
                    capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('HQ_PREPARE_ASSET_OK',result.stdout)
            payload=struct.pack('<II',0x34600,8+97*208)+bytes(8)+bytes([0xa5])*97*208
            check(payload,True)
            check(payload[:-1],False)
            check(struct.pack('<I',0x34601)+payload[4:],False)
            check(payload[:4]+struct.pack('<I',8+96*208)+payload[8:],False)


if __name__ == '__main__':
    unittest.main()
