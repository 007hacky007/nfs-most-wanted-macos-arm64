# Most Wanted native Metal port

Local native prototype of the supplied PC v1.3 game for Apple Silicon, with a Direct3D 9 to Metal runtime adapted from the sibling NFSU2 project. Game instructions are compiled into ARM64; the runtime does not use Wine, Rosetta, or an x86 interpreter. The original backup stays unchanged.

Observed working: original menus, Quick Race, throttle/steering, pause/restart/return, profile creation/reload, native audio and music, complete attract movie, opening story movie, and the following in-engine scene/career race. The packaged app completed a race session beyond ten minutes and then restarted, returned to the menu, and quit normally. Full-career and every-car coverage remain unverified; unknown generated audio code stops for a native rebuild. Evidence and acceptance results are in [the implementation plan](docs/superpowers/plans/2026-10-28-native-metal.md).

## Run the local app

Open `out/Most Wanted.app` and select the extracted `game` folder. Click the title screen to continue. Use arrows and Enter in menus, arrows to drive, and Esc to pause. The window close button and Cmd-Q request a normal game shutdown.

The app keeps saves under `~/Library/Application Support/NFSMW/Saves` and its latest log at `~/Library/Logs/NFSMW/last-run.log`. It reads the selected game folder without writing into it. Network play is disabled. A generic `NAME` profile was used for local verification; the game can create additional aliases.

## Build locally

Requires an Apple Silicon Mac, Xcode command-line tools, Python 3, and `cabextract`. The input folder must contain the four supplied MODE1/2352 discs and the update ZIP.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/install_game.py game_backup game
./gen.sh
./build.sh
./pack.sh
```

The supported executable SHA-256 is `80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c`. The installer extracts and verifies the required x86 D3DX DLL from the original DirectX cabinet. It does not run Windows installers or bundled utilities.

Development launch:

```sh
WINDOW=1 NFSRES=1280x960 ALARM=0 out/nfsmw_boot game/speed.exe
```

`ALARM` is the command-line development time limit in seconds; zero disables it. Command-line saves and registry data go under `out/profile/`. `NFSMW_SAVEDIR` overrides the save directory. `NOFOCUS=2` makes a test window invisible; omit it for normal play. `NFSU2_MUTE=1` silences speakers while keeping native mixing and audio capture active.

The sandbox used by development tools can hide Metal and audio devices; run the engine normally to access the actual hardware.

## Generated audio callbacks

The original game generates small x86 callbacks at runtime. This port uses precompiled native templates for observed callback shapes. An unknown callback stops with a diagnostic and a local code capture; it does not invoke an x86 interpreter.

To compile a captured callback into the next native build:

```sh
.venv/bin/python tools/lift_callbacks.py --capture --arena
./build.sh
./pack.sh
```

The capture tool accepts bounded callbacks with internal forward branches. It rejects backward/indirect branches, external branch targets, and internal/indirect calls. Relative call operands are read from the current callback so the native template remains correct at another guest address. All other instruction bytes must match, and every crossed memory page must be committed. `--arena` collects additional validated audio callbacks from the captured code area. Captures and generated code remain in ignored local directories and must be regenerated from your own game.

For a new build, `tools/profile_callbacks.py --script tests/input/menu.txt` can collect startup templates automatically. After creating an alias, use `tests/input/quickrace.txt` to exercise race loading. These are bring-up inputs; inspect the resulting game screen rather than assuming a timed script reached its target. An app capture is stored under `~/Library/Application Support/NFSMW/out`; copy its `missing-code*` files into the workspace's `out/` before rebuilding.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/isatest.py
clang -O1 -Wno-unused-label -Iruntime gen/isatest.c runtime/mem.c -lm -o out/isatest
out/isatest
out/nfsmw_boot --test-kernel
clang -O1 -Iruntime tests/shader_ps20.c runtime/vsemu.c -lm -o out/shader-ps20-test
out/shader-ps20-test
```

`tests/abi.c` and `tests/msvcrt.c` provide additional native ABI/CRT harnesses. Runtime verification logs and game-frame captures stay under ignored `out/` paths.

The donor source's personal-use terms are preserved in [LICENSE](LICENSE), with its imported notice in [third_party/nfsu2-web-LICENSE](third_party/nfsu2-web-LICENSE). Nothing has been published.
