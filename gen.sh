#!/bin/sh
set -eu
cd "$(dirname "$0")"
PY=.venv/bin/python
GAME_DIR=${1:-game}
mkdir -p out gen/all gen/d3dx
unset OVERRIDE HOOKS BRANCH_HOOKS FTOL2INL FLAGABI INLINE_LIST CODE_RVA_START
export X87PC=1
"$PY" tools/target.py "$GAME_DIR"
read -r IMAGE < out/target-image.txt
"$PY" - <<'PY' > out/widescreen-hooks.txt
from pathlib import Path
import re
sources = [path.read_text() for path in Path('runtime').glob('mw_*.c')]
sites = [site for source in sources
         for site in re.findall(r'HOOK_SITE\((0x[0-9a-fA-F]+)\)', source)]
branches = {}
for source in sources:
    for site, target in re.findall(r'HOOK_BRANCH\((0x[0-9a-fA-F]+)\s*,\s*(0x[0-9a-fA-F]+)\)', source):
        site, target = int(site, 16), int(target, 16)
        if site in branches:
            raise ValueError('duplicate native branch declaration')
        branches[site] = target
Path('out/native-branches.txt').write_text(','.join(f'{site:08x}:{target:08x}' for site,target in sorted(branches.items())) + '\n')
print(','.join(sorted(set(sites))))
PY
read -r HOOKS < out/widescreen-hooks.txt
read -r BRANCH_HOOKS < out/native-branches.txt
export HOOKS BRANCH_HOOKS
"$PY" tools/genall.py "$IMAGE" 128 > out/generate-game.log 2>&1
STRICT=1 "$PY" tools/argcount.py "$IMAGE" > out/imports-game.log 2>&1
unset HOOKS BRANCH_HOOKS
"$PY" tools/prepare_module.py "$GAME_DIR/d3dx9_26.dll" 0x02000000 out/d3dx gen/d3dx dx_ > out/prepare-d3dx.log
CODE_RVA_START=0x2a005 GENOUT=gen/d3dx RELOCS=out/d3dx/relocs.txt SEEDS=out/d3dx/seeds.txt SYMPFX=dx_ \
    "$PY" tools/genall.py out/d3dx/image.dll 64 > out/generate-d3dx.log 2>&1
CODE_RVA_START=0x2a005 RELOCS=out/d3dx/relocs.txt IMPOUT=gen/d3dx/impargs.c SYMPFX=dx_ STRICT=1 IMPDLL="$GAME_DIR/d3dx9_26.dll" \
    "$PY" tools/argcount.py out/d3dx/image.dll > out/imports-d3dx.log 2>&1
echo "Generated Most Wanted and D3DX; see out/generate-*.log"
