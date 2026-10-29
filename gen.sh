#!/bin/sh
set -eu
cd "$(dirname "$0")"
PY=.venv/bin/python
mkdir -p out gen/all gen/d3dx
unset OVERRIDE HOOKS FTOL2INL FLAGABI INLINE_LIST CODE_RVA_START
export X87PC=1
"$PY" tools/target.py game
"$PY" tools/genall.py game/speed.exe 128 > out/generate-game.log 2>&1
STRICT=1 "$PY" tools/argcount.py game/speed.exe > out/imports-game.log 2>&1
"$PY" tools/prepare_module.py game/d3dx9_26.dll 0x02000000 out/d3dx gen/d3dx dx_ > out/prepare-d3dx.log
CODE_RVA_START=0x2a005 GENOUT=gen/d3dx RELOCS=out/d3dx/relocs.txt SEEDS=out/d3dx/seeds.txt SYMPFX=dx_ \
    "$PY" tools/genall.py out/d3dx/image.dll 64 > out/generate-d3dx.log 2>&1
CODE_RVA_START=0x2a005 RELOCS=out/d3dx/relocs.txt IMPOUT=gen/d3dx/impargs.c SYMPFX=dx_ STRICT=1 IMPDLL=game/d3dx9_26.dll \
    "$PY" tools/argcount.py out/d3dx/image.dll > out/imports-d3dx.log 2>&1
echo "Generated Most Wanted and D3DX; see out/generate-*.log"
