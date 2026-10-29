#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 - <<'PY'
from pathlib import Path
import plistlib,shutil
app=Path('out/Most Wanted.app/Contents')
(app/'MacOS').mkdir(parents=True,exist_ok=True)
(app/'Resources').mkdir(exist_ok=True)
shutil.copy2('out/nfsmw_boot',app/'MacOS/MostWanted')
for source in ('LICENSE','third_party/nfsu2-web-LICENSE'):
    shutil.copy2(source,app/'Resources'/Path(source).name)
info={'CFBundleExecutable':'MostWanted','CFBundleIdentifier':'local.nfsmw.native',
      'CFBundleName':'Most Wanted','CFBundleDisplayName':'Most Wanted',
      'CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'0.1.0',
      'LSMinimumSystemVersion':'11.0','NSHighResolutionCapable':True,
      'NSPrincipalClass':'NSApplication','NSQuitAlwaysKeepsWindows':False}
(app/'Info.plist').write_bytes(plistlib.dumps(info))
PY
codesign --force --sign - 'out/Most Wanted.app'
echo 'Packaged out/Most Wanted.app'
