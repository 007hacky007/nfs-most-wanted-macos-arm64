"""Check startup feedback and deferred alpha variants in the native renderer."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform=='darwin','requires native macOS')
class LoadingTests(unittest.TestCase):
    def run_probe(self,mode):
        with tempfile.TemporaryDirectory() as temporary:
            binary=Path(temporary)/'loading'
            command=['clang','-fobjc-arc',str(ROOT/'tests/backend_loading.m'),'-I'+str(ROOT/'runtime'),
                     str(ROOT/'runtime/vsemu.c'),'-Wl,-undefined,dynamic_lookup']
            for framework in ('Foundation','Metal','AppKit','QuartzCore','GameController','IOKit'):
                command+=['-framework',framework]
            result=subprocess.run([*command,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            capture=ROOT/'out/loading-test.png';capture.parent.mkdir(exist_ok=True)
            result=subprocess.run([str(binary),mode,str(capture)],capture_output=True,text=True,timeout=30)
            if result.returncode==77:self.skipTest('Metal device unavailable')
            self.assertEqual(result.returncode,0,result.stderr)
            return result.stdout

    def test_unused_alpha_variants_are_deferred(self):
        self.assertIn('compile once',self.run_probe('shader'))

    @unittest.skipUnless(os.environ.get('NFSMW_TEST_GUI'),'set NFSMW_TEST_GUI for Cocoa loading UI')
    def test_blank_frame_does_not_dismiss_loading_screen(self):
        self.assertIn('hides after content',self.run_probe('ui'))

    @unittest.skipUnless(os.environ.get('NFSMW_TEST_GUI'),'set NFSMW_TEST_GUI for Cocoa window events')
    def test_fixed_resolution_survives_window_and_space_transitions(self):
        for mode in ('pinned','dynamic'):
            with self.subTest(mode=mode):
                self.assertIn('preserve fixed-resolution resources',self.run_probe(mode))
