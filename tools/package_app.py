"""Package a native executable and its private game copy into a self-contained app, atomically."""
import argparse
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import tempfile

import pefile

ROOT=Path(__file__).resolve().parents[1]
BUNDLE_ID='local.nfsmw.native'


def windows_icon(executable):
    """Read the original ICO from the supplied game's PE resources."""
    try:
        pe=pefile.PE(str(executable))
    except pefile.PEFormatError as error:
        raise ValueError('cannot read the supplied game icon') from error
    try:
        resources={entry.id:entry for entry in
                   getattr(getattr(pe,'DIRECTORY_ENTRY_RESOURCE',None),'entries',[])}
        if 3 not in resources or 14 not in resources:
            raise ValueError('supplied game executable has no Windows app icon')
        def read(entry):
            resource=entry.directory.entries[0].data.struct
            data=pe.get_data(resource.OffsetToData,resource.Size)
            if len(data)!=resource.Size:
                raise ValueError('incomplete Windows app icon resource')
            return data
        group=read(resources[14].directory.entries[0])
        if len(group)<6:
            raise ValueError('invalid Windows app icon group')
        reserved,kind,count=struct.unpack_from('<HHH',group)
        if (reserved,kind)!=(0,1) or not count or len(group)!=6+14*count:
            raise ValueError('invalid Windows app icon group')
        images={entry.id:entry for entry in resources[3].directory.entries}
        directory,payload=bytearray(group[:6]),bytearray()
        for index in range(count):
            width,height,colors,reserved,planes,bits,size,identifier=struct.unpack_from(
                '<BBBBHHIH',group,6+14*index)
            if identifier not in images:
                raise ValueError('missing Windows app icon image')
            bitmap=read(images[identifier])
            if len(bitmap)!=size:
                raise ValueError('Windows app icon image size differs')
            directory.extend(struct.pack('<BBBBHHII',width,height,colors,reserved,
                                         planes,bits,size,6+16*count+len(payload)))
            payload.extend(bitmap)
        return bytes(directory+payload)
    except (IndexError,AttributeError,struct.error) as error:
        raise ValueError('invalid Windows app icon resources') from error
    finally:
        pe.close()


def write_app_icon(icon,destination):
    destination=Path(destination)
    with tempfile.TemporaryDirectory(prefix='.icon-',dir=destination.parent) as temporary:
        source=Path(temporary)/'original.ico';source.write_bytes(icon)
        subprocess.run(['sips','-s','format','icns',str(source),'--out',str(destination)],
                       check=True,capture_output=True)


# The launcher refuses an app whose Contents/Resources/game lacks these (runtime/launcher.m).
REQUIRED_GAME_FILES=('speed.exe','d3dx9_26.dll')
# Info.plist key with the NFSMW Builder version that built the app; the launcher compares it
# with the latest release. A Terminal build has none.
BUILDER_VERSION_KEY='NFSBuilderVersion'
VERSION=re.compile(r'[0-9]+(\.[0-9]+){0,3}(-[A-Za-z0-9.]+)?')


def copy_game(game,target):
    """The whole installed tree, as APFS clones where the volume can (else a copy). Extended
    attributes come along, so a download's quarantine stays on the files from the player's
    copy; only Finder info and resource forks go, which codesign --strict refuses in a bundle."""
    if subprocess.run(['/bin/cp','-c','-R',str(game),str(target)],capture_output=True).returncode:
        shutil.rmtree(target,ignore_errors=True)
        shutil.copytree(game,target,copy_function=shutil.copyfile)
    for name in ('com.apple.FinderInfo','com.apple.ResourceFork'):
        subprocess.run(['/usr/bin/xattr','-dr',name,str(target)],capture_output=True)


def package_app(binary,game,output=Path('out/NFSMW.app'),builder_version=None):
    binary,output=Path(binary),Path(output)
    if builder_version is not None and not VERSION.fullmatch(builder_version):
        raise ValueError('builder version must look like 1.2.3')
    if binary.is_symlink() or not binary.is_file():raise ValueError('native executable must be a regular file, not a symlink')
    with binary.open('rb')as stream:header=stream.read(8)
    if header!=struct.pack('<II',0xfeedfacf,0x0100000c):raise ValueError('expected a native ARM64 Mach-O executable')
    if output.is_symlink():raise ValueError('app destination must not be a symlink')
    if output.exists():
        info=output/'Contents/Info.plist'
        if info.is_symlink() or not info.is_file() or plistlib.loads(info.read_bytes()).get('CFBundleIdentifier')!=BUNDLE_ID:
            raise FileExistsError('refusing to replace an unrelated app or folder')
    # The app carries all game data and never reads a game folder elsewhere.
    if game is None:raise ValueError('a prepared game folder is required: the app must contain the game')
    game=Path(game)
    if game.is_symlink() or not game.is_dir():raise ValueError('game folder must be a folder, not a symlink')
    if output.parent.resolve().is_relative_to(game.resolve()):raise ValueError('app output must be outside the game folder')
    for name in REQUIRED_GAME_FILES:
        if (game/name).is_symlink() or not (game/name).is_file():
            raise ValueError(f'game folder has no {name}; it must be a prepared game folder')
    for path in game.rglob('*'):
        if path.is_symlink():raise ValueError('game symlinks cannot be included in the app')
    icon=windows_icon(game/'speed.exe')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.nfsmw-app-',dir=output.parent)as temporary:
        temporary=Path(temporary);staged=temporary/'NFSMW.app';contents=staged/'Contents'
        executable=contents/'MacOS/NFSMW';executable.parent.mkdir(parents=True)
        resources=contents/'Resources';resources.mkdir()
        shutil.copyfile(binary,executable);executable.chmod(0o755)
        for relative in ('LICENSE','third_party/nfsu2-web-LICENSE','third_party/WidescreenFix-LICENSE'):
            shutil.copyfile(ROOT/relative,resources/Path(relative).name)
        copy_game(game,resources/'game')
        info={'CFBundleExecutable':'NFSMW','CFBundleIdentifier':BUNDLE_ID,
              'CFBundleName':'NFSMW','CFBundleDisplayName':'NFSMW',
              'CFBundlePackageType':'APPL','CFBundleVersion':'9','CFBundleShortVersionString':'0.3.6',
              'LSMinimumSystemVersion':'11.0','NSHighResolutionCapable':True,
              'NSPrincipalClass':'NSApplication','NSQuitAlwaysKeepsWindows':False}
        write_app_icon(icon,resources/'NFSMW.icns')
        info['CFBundleIconFile']='NFSMW.icns'
        if builder_version is not None:info[BUILDER_VERSION_KEY]=builder_version
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
    parser.add_argument('--game',type=Path,required=True,
                        help='prepared game folder (for example out/installed); it is copied into the app')
    parser.add_argument('--output',type=Path,default=Path('out/NFSMW.app'))
    arguments=parser.parse_args()
    package_app(arguments.binary,arguments.game,arguments.output)
    print('Packaged NFSMW.app')
