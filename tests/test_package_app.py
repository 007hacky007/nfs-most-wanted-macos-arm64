"""Packaging keeps the last usable app until its replacement is signed."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tests.test_app_icon import synthetic_icon


@unittest.skipUnless(sys.platform=='darwin','requires native macOS signing')
class PackageAppTests(unittest.TestCase):
    def setUp(self):
        # Icon extraction is exercised separately; keep copying/signing real here.
        reader=patch('tools.package_app.windows_icon',return_value=synthetic_icon())
        reader.start();self.addCleanup(reader.stop)

    def fixture(self,root):
        source=root/'main.c';source.write_text('int main(void){return 0;}\n')
        binary=root/'native'
        subprocess.run(['clang','-arch','arm64',str(source),'-o',str(binary)],check=True,capture_output=True)
        game=root/'game';game.mkdir();(game/'speed.exe').write_bytes(b'owned test payload')
        (game/'d3dx9_26.dll').write_bytes(b'owned test library')
        return binary,game,root/'NFSMW.app'

    def test_signed_app_contains_private_game_copy_and_native_binary(self):
        from tools.package_app import package_app
        with tempfile.TemporaryDirectory()as temporary:
            binary,game,output=self.fixture(Path(temporary))
            original=binary.read_bytes()
            package_app(binary,game,output)
            self.assertEqual((output/'Contents/Resources/game/speed.exe').read_bytes(),b'owned test payload')
            subprocess.run([str(output/'Contents/MacOS/NFSMW')],check=True,capture_output=True)
            self.assertEqual(binary.read_bytes(),original)
            info=plistlib.loads((output/'Contents/Info.plist').read_bytes())
            self.assertEqual(info['CFBundleExecutable'],'NFSMW')
            self.assertEqual(info['CFBundleName'],'NFSMW')
            self.assertEqual(info['CFBundleDisplayName'],'NFSMW')
            self.assertNotIn('NFSBuilderVersion',info)
            icon=output/'Contents/Resources'/info['CFBundleIconFile']
            self.assertEqual(icon.read_bytes()[:4],b'icns')
            subprocess.run(['codesign','--verify','--deep','--strict',str(output)],check=True,capture_output=True)
            self.assertEqual((game/'speed.exe').read_bytes(),b'owned test payload')

    def test_the_whole_game_goes_in_and_its_quarantine_stays(self):
        """Everything in the installed tree goes in, without execute permission. Files from the
        player's copy keep their quarantine, also when the clone fails and it is copied; Finder
        info, which codesign --strict refuses, does not come along."""
        from tools.package_app import copy_keeping_quarantine,package_app
        with tempfile.TemporaryDirectory()as temporary:
            binary,game,output=self.fixture(Path(temporary))
            (game/'DirectX').mkdir();(game/'DirectX/DXSETUP.exe').write_bytes(b'windows extra')
            (game/'.nfsmw').mkdir();(game/'.nfsmw/runtime.exe').write_bytes(b'derived')
            mark='0081;00000000;Test;'
            subprocess.run(['/usr/bin/xattr','-w','com.apple.quarantine',mark,str(game/'DirectX/DXSETUP.exe')],check=True)
            subprocess.run(['/usr/bin/xattr','-wx','com.apple.FinderInfo','00'*31+'01',str(game/'speed.exe')],check=True)
            (game/'DirectX/DXSETUP.exe').chmod(0o755)
            run=subprocess.run
            def no_clone(command,*args,**kwargs):
                if command[:2]==['/bin/cp','-c']:return subprocess.CompletedProcess(command,1)
                return run(command,*args,**kwargs)
            for clone in (True,False):
                with self.subTest(clone=clone),patch('subprocess.run',run if clone else no_clone), \
                        patch('tools.package_app.copy_keeping_quarantine',wraps=copy_keeping_quarantine)as fallback:
                    package_app(binary,game,output)
                    self.assertEqual(fallback.called,not clone)
                    bundled=output/'Contents/Resources/game'
                    self.assertEqual(sorted(p.relative_to(bundled).as_posix() for p in bundled.rglob('*') if p.is_file()),
                                     ['.nfsmw/runtime.exe','DirectX/DXSETUP.exe','d3dx9_26.dll','speed.exe'])
                    found=run(['/usr/bin/xattr','-p','com.apple.quarantine',str(bundled/'DirectX/DXSETUP.exe')],
                              capture_output=True,text=True)
                    self.assertEqual(found.stdout.strip(),mark)
                    self.assertFalse(any(p.stat().st_mode&0o111 for p in bundled.rglob('*') if p.is_file()),
                                     'no game file is executable')
                    self.assertTrue(game.joinpath('DirectX/DXSETUP.exe').stat().st_mode&0o100,'the source is only read')
                    run(['codesign','--verify','--deep','--strict',str(output)],check=True,capture_output=True)

    def test_failed_replacement_and_symlink_inputs_preserve_existing_app(self):
        from tools.package_app import package_app
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);binary,game,output=self.fixture(root)
            package_app(binary,game,output)
            sentinel=output/'Contents/Resources/game/speed.exe'
            real_run=subprocess.run
            def failed_sign(command,**kwargs):
                if command[0]=='codesign':raise subprocess.CalledProcessError(1,command)
                return real_run(command,**kwargs)
            with patch('tools.package_app.subprocess.run',side_effect=failed_sign):
                with self.assertRaises(subprocess.CalledProcessError):package_app(binary,game,output)
            self.assertEqual(sentinel.read_bytes(),b'owned test payload')
            with patch('tools.package_app.windows_icon',side_effect=ValueError('missing icon')):
                with self.assertRaisesRegex(ValueError,'icon'):package_app(binary,game,output)
            self.assertEqual(sentinel.read_bytes(),b'owned test payload')
            (game/'link').symlink_to(binary)
            with self.assertRaisesRegex(ValueError,'symlink'):package_app(binary,game,output)
            self.assertEqual(sentinel.read_bytes(),b'owned test payload')
            self.assertFalse(list(root.glob('.nfsmw-app-*')))

    def test_builder_version_is_stamped_for_the_update_check(self):
        from tools.package_app import package_app
        with tempfile.TemporaryDirectory()as temporary:
            binary,game,output=self.fixture(Path(temporary))
            package_app(binary,game,output,builder_version='0.4.0')
            info=plistlib.loads((output/'Contents/Info.plist').read_bytes())
            self.assertEqual(info['NFSBuilderVersion'],'0.4.0')
            subprocess.run(['codesign','--verify','--deep','--strict',str(output)],check=True,capture_output=True)
            for bad in ('','v1.0','1.0;rm','../1'):
                with self.subTest(bad),self.assertRaisesRegex(ValueError,'builder version'):
                    package_app(binary,game,output,builder_version=bad)
            self.assertEqual(plistlib.loads((output/'Contents/Info.plist').read_bytes())['NFSBuilderVersion'],'0.4.0')

    def test_app_without_game_data_is_refused(self):
        from tools.package_app import package_app
        with tempfile.TemporaryDirectory()as temporary:
            root=Path(temporary);binary,game,output=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'game folder is required'):package_app(binary,None,output)
            (game/'d3dx9_26.dll').unlink()
            with self.assertRaisesRegex(ValueError,'d3dx9_26.dll'):package_app(binary,game,output)
            empty=root/'empty';empty.mkdir()
            with self.assertRaisesRegex(ValueError,'speed.exe'):package_app(binary,empty,output)
            self.assertFalse(output.exists())
            command=subprocess.run([sys.executable,'tools/package_app.py','--binary',str(binary),'--output',str(output)],
                                   capture_output=True,text=True)
            self.assertEqual(command.returncode,2)
            self.assertIn('--game',command.stderr)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
