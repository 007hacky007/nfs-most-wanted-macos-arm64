"""Package a native executable and an optional private game copy atomically."""
import argparse
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
BUNDLE_ID='local.nfsmw.native'


def package_app(binary,game=None,output=Path('out/Most Wanted.app')):
    binary,output=Path(binary),Path(output)
    if binary.is_symlink() or not binary.is_file():raise ValueError('native executable must be a regular file, not a symlink')
    with binary.open('rb')as stream:header=stream.read(8)
    if header!=struct.pack('<II',0xfeedfacf,0x0100000c):raise ValueError('expected a native ARM64 Mach-O executable')
    if output.is_symlink():raise ValueError('app destination must not be a symlink')
    if output.exists():
        info=output/'Contents/Info.plist'
        if info.is_symlink() or not info.is_file() or plistlib.loads(info.read_bytes()).get('CFBundleIdentifier')!=BUNDLE_ID:
            raise FileExistsError('refusing to replace an unrelated app or folder')
    if game is not None:
        game=Path(game)
        if game.is_symlink() or not game.is_dir():raise ValueError('game folder must not be a symlink')
        if output.parent.resolve().is_relative_to(game.resolve()):raise ValueError('app output must be outside the game folder')
        for path in game.rglob('*'):
            if path.is_symlink():raise ValueError('game symlinks cannot be included in the app')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nfsmw-app-',dir=output.parent)as temporary:
        temporary=Path(temporary);staged=temporary/'Most Wanted.app';contents=staged/'Contents'
        executable=contents/'MacOS/MostWanted';executable.parent.mkdir(parents=True)
        resources=contents/'Resources';resources.mkdir()
        shutil.copyfile(binary,executable);executable.chmod(0o755)
        for relative in ('LICENSE','third_party/nfsu2-web-LICENSE','third_party/WidescreenFix-LICENSE'):
            shutil.copyfile(ROOT/relative,resources/Path(relative).name)
        if game is not None:shutil.copytree(game,resources/'game',copy_function=shutil.copyfile)
        info={'CFBundleExecutable':'MostWanted','CFBundleIdentifier':BUNDLE_ID,
              'CFBundleName':'Most Wanted','CFBundleDisplayName':'Most Wanted',
              'CFBundlePackageType':'APPL','CFBundleVersion':'3','CFBundleShortVersionString':'0.3.0',
              'LSMinimumSystemVersion':'11.0','NSHighResolutionCapable':True,
              'NSPrincipalClass':'NSApplication','NSQuitAlwaysKeepsWindows':False}
        (contents/'Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['codesign','--force','--sign','-',str(staged)],check=True,capture_output=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(staged)],check=True,capture_output=True)
        previous=temporary/'previous.app'
        if output.exists():output.rename(previous)
        try:staged.rename(output)
        except BaseException:
            if previous.exists():previous.rename(output)
            raise
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,default=Path('out/nfsmw_boot'))
    parser.add_argument('--game',type=Path)
    parser.add_argument('--output',type=Path,default=Path('out/Most Wanted.app'))
    arguments=parser.parse_args()
    package_app(arguments.binary,arguments.game,arguments.output)
    print('Packaged Most Wanted.app')
