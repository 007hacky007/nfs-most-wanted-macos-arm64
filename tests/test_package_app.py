"""Packaging keeps the last usable app until its replacement is signed."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform=='darwin','requires native macOS signing')
class PackageAppTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'main.c';source.write_text('int main(void){return 0;}\n')
        binary=root/'native'
        subprocess.run(['clang','-arch','arm64',str(source),'-o',str(binary)],check=True,capture_output=True)
        game=root/'game';game.mkdir();(game/'speed.exe').write_bytes(b'owned test payload')
        return binary,game,root/'Most Wanted.app'

    def test_signed_app_contains_private_game_copy_and_native_binary(self):
        from tools.package_app import package_app
        with tempfile.TemporaryDirectory()as temporary:
            binary,game,output=self.fixture(Path(temporary))
            original=binary.read_bytes()
            package_app(binary,game,output)
            self.assertEqual((output/'Contents/Resources/game/speed.exe').read_bytes(),b'owned test payload')
            subprocess.run([str(output/'Contents/MacOS/MostWanted')],check=True,capture_output=True)
            self.assertEqual(binary.read_bytes(),original)
            info=plistlib.loads((output/'Contents/Info.plist').read_bytes())
            self.assertEqual(info['CFBundleExecutable'],'MostWanted')
            subprocess.run(['codesign','--verify','--deep','--strict',str(output)],check=True,capture_output=True)
            self.assertEqual((game/'speed.exe').read_bytes(),b'owned test payload')

    def test_failed_replacement_and_symlink_inputs_preserve_existing_app(self):
        from tools.package_app import package_app
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);binary,game,output=self.fixture(root)
            package_app(binary,game,output)
            sentinel=output/'Contents/Resources/game/speed.exe'
            with patch('tools.package_app.subprocess.run',side_effect=subprocess.CalledProcessError(1,['codesign'])):
                with self.assertRaises(subprocess.CalledProcessError):package_app(binary,game,output)
            self.assertEqual(sentinel.read_bytes(),b'owned test payload')
            (game/'link').symlink_to(binary)
            with self.assertRaisesRegex(ValueError,'symlink'):package_app(binary,game,output)
            self.assertEqual(sentinel.read_bytes(),b'owned test payload')
            self.assertFalse(list(root.glob('.nfsmw-app-*')))


if __name__=='__main__':unittest.main()
