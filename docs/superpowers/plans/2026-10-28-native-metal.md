# Native Most Wanted Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. The user authorized implementation with "go"; continue inline without another approval gate.

**Goal:** Reach the original menu and a playable race in the supplied PC game as an ARM64 application using Metal.

**Architecture:** Snapshot the relevant NFSU2 source, translate the fingerprinted game and D3DX DLL into separate native modules, and adapt the Windows/D3D9 runtime. Establish executable behavior before packaging the application.

**Tech Stack:** Python 3, pefile, Capstone 5, C/Objective-C, Clang ARM64, AppKit, Metal, CoreAudio, GameController.

**Spec:** `docs/superpowers/specs/2026-10-28-native-metal-design.md`

## Global constraints

- Original PC menu and Quick Race are acceptance targets; an asset viewer or test triangle is insufficient.
- Native ARM64 and direct Metal; no Wine, Rosetta, browser, or runtime x86 interpreter.
- Pin the executable and D3DX hashes from the spec before translation/loading.
- Preserve original backups and leave the sibling NFSU2 working tree untouched.
- No personal identities, publication, or external posting. No commits until a suitable repository identity is authorized; this initially empty repository has no remote or HEAD.
- Ignore game data, generated game code, binary products, and private donor snapshots.
- Use only ASCII hyphens in generated prose.

## Review focus

1. Truncated raw sectors and misleading archive names must not install corrupt data.
2. Archive path traversal and symlinks must not escape the extraction directory.
3. An x64 DLL sharing the required basename must be rejected.
4. NFSU2 addresses must not dispatch hooks in Most Wanted accidentally.
5. Cdecl, stdcall, callbacks, and x87 return values must preserve the guest stack and registers.

## Tasks

### Task 1: Install and fingerprint local inputs

Files: `tools/install_game.py`, `tests/test_install.py`, `.gitignore`, `requirements.txt`.

Interfaces: `RawISO(path, base=0, size=None)` supplies seekable logical ISO bytes; `disc_files(path)` returns named file extents; `install(backup, destination)` installs validated inputs into a new directory.

- [x] Write and run failing tests for cross-sector reads, truncated input, ISO/Joliet directory decoding, ZIP traversal, wrong binary fingerprint, and output preservation on extraction failure.
- [x] Implement raw-sector/ISO reading, CRC-checked ZIP extraction, and x86 cabinet selection without executing Windows programs.
- [x] Run `python3 -m unittest discover -s tests -v`; all installer tests pass.
- [x] Install the supplied discs into `game/`, verify both exact binary hashes and record extracted file counts.

### Task 2: Adapt code discovery and native generation

Files: `tools/lift.py`, `tools/genall.py`, `tools/argcount.py`, `tools/prepare_module.py`, `tools/target.py`, `gen.sh`, donor source notices/manifest, `tests/test_target.py`.

Interfaces: target metadata supplies game ranges and hidden relocation slots; D3DX analysis image loads at `0x02000000`; generated outputs live in `gen/all` and `gen/d3dx`, with distinct function symbols/tables.

- [x] Snapshot selected donor sources and notices with a SHA-256 manifest; do not import game files or generated code from NFSU2.
- [x] Write failing tests for whitespace relocation sections, malformed fixups, target-specific compiler behavior, and non-overlapping module placement.
- [x] Implement target-driven generation, disable donor-specific hooks/return assumptions, generate both modules, and report real coverage/traps.
- [x] Compile all generated shards for Apple Silicon, run applicable ISA tests, and record actual results.

### Task 3: Execute the game and D3DX startup

Files: `runtime/cpu.h`, `runtime/mem.c`, `runtime/dispatch.c`, `runtime/module.c`, `runtime/win32.c`, `runtime/win32_ext.c`, `runtime/heap.c`, `runtime/fileio.c`, `runtime/msvcrt.c`, `runtime/main.c`, `build.sh`, `tests/abi.c`.

Interfaces: native main loads the game at `0x00400000`, initializes TEB/PEB/stack and Windows imports, loads the fingerprinted D3DX module, and dispatches entry `0x007c4040`; traces identify unsupported reached operations.

- [x] Write/run failing ABI and module tests for stack cleanup, symbol resolution, callbacks, x87 results, image bounds, and rejected DLL fingerprints.
- [x] Integrate donor mechanisms, replacing Most Wanted-specific ranges and removing unverified game hooks.
- [x] Bind D3DX imports, run DLL attach, implement reached CRT/Windows services, and execute the game entry under a time limit.
- [x] Investigate each execution failure from its trace and add focused checks before fixes; do not mask unresolved operations as success.

### Task 4: Render and control the original menu

Files: `runtime/com.c`, `runtime/metal.m`, `runtime/vsemu.c`, native input adapters, `runtime/main.c`, `tests/shader_ps20.c`.

Interfaces: lifted effect COM calls reach the native D3D9 device; its shader/resource/draw operations submit to Metal on the main-thread window loop.

- [x] Verify effect creation and shader translation against real game calls, then fix observed state/resource failures.
- [x] Render the original menu, navigate with keyboard, and save screenshots with the matching runtime log.
- [x] Verify actual Metal use and native ARM64 executable architecture.

### Task 5: Play, hear, and save a race

Files: native audio adapters, input/timing/save integrations, Most Wanted-specific verified hooks, `tools/autorun.py` and focused regression checks.

Interfaces: original game logic controls Quick Race, guest audio reaches native playback, and writes use isolated Most Wanted save/registry paths.

- [x] Start Quick Race; resolve actual gameplay/render/audio failures with reproductions.
- [x] Verify keyboard control, pause/restart/return, sound, and profile persistence after restart.
- [x] Run the ten-minute acceptance session; record memory samples, screenshots, and unresolved limitations.

### Task 6: Package and review the usable application

Files: `runtime/app.m`, `pack.sh`, `README.md`, source notices, verification record in this plan.

- [x] Package the proven engine with a local folder picker and separate Most Wanted save paths.
- [x] Repeat menu/race acceptance through the `.app`; do not substitute standalone engine results.
- [x] Request one independent code review of the integrated changes, fix material findings, and repeat affected checks.
- [x] Report observed functionality and any unfinished work accurately. Keep the entire result local.

## Progress and decisions

- Scope update: the user requires sound, music, videos, and cutscenes in the usable milestone. Verify them explicitly alongside menu/race acceptance.

- 2026-10-28: User approved the design. Inline execution selected to avoid additional coordination gates.
- Ruling: Use the new dedicated workspace in place. There is no HEAD or existing source branch to isolate with a worktree; leave the unrelated NFSU2 checkout untouched. No commits or git identity changes are needed to implement and test locally.
- Pre-flight: Tasks 1-3 share the exact binary hashes, module base, generated table prefixes, and image metadata. Tasks 3-5 share the CPU/COM ABI. Keep these values in target metadata and shared headers.

- Task 1: complete. Seven installer tests passed; four supplied archives extracted with CRC verification (1,406 files); exact game/D3DX hashes verified. Original backup untouched.
- Task 2: generation complete. Game: 35,716 entries, 111.0 MB C, 308 static traps, zero truncated targets. D3DX: 7,650 entries, 71.0 MB C, 135 static traps, zero truncated targets. Compilation in progress; trap reachability remains unknown.
- Compiler/runtime checks: 12 Python checks and all 610 donor ISA checks passed. Callback ABI harness linked against the actual COM object passed cdecl/stdcall argument and CPU/x87 preservation checks.
- Ruling: D3DX's merged `.text` contains a constant prefix. For the exact supported hash, executable instructions start at RVA `0x2a005`; exclude the preceding constant bytes from code discovery while keeping them mapped as data. A regression check covers the lifter range adjustment.
- Ruling: Reserve D3DX at `0x02000000` and move DLL heaps to `0x03000000` through `0x0f000000`. The donor DLL heap allocator would otherwise overlap the translated image. Placement tests reject the heap boundary.
- Ruling: Remove fallback instruction interpretation from indirect dispatch and stop immediately on unresolved native code or reached unsupported imports. Diagnostic bring-up must not quietly execute a non-native fallback or manufacture successful API results.
- Task 2: ARM64 compilation and linkage complete. After adding LOCK-prefix handling, game static traps fell to 296. All 620 ISA checks pass; static trap reachability beyond the exercised startup remains unverified.
- Task 3: Game CRT and supplied D3DX DLL initialize successfully. Added tested MSVCRT allocation/initialization/qsort/control-word/string adapters and Windows waitable timer/date services. The native callback ABI harness passed.
- Task 4: Actual Apple M1 Pro Metal device and CoreAudio speaker output opened outside the tool sandbox. Captured the original EA logo, intro movie, and Most Wanted title screen. This is game output, not a replacement UI. Menu/race acceptance is not complete.
- Ruling: The game generates audio callbacks in heap memory. Compile captured straight-line callback shapes into native ARM64 templates at build time, match their instruction bytes before calling them, and read only relative call operands as parameters. No runtime x86 interpreter was restored. Unseen/branching shapes stop for analysis; full callback coverage is not yet established.
- Native generated-code checks: three tests cover rebased calls, refusal of unbounded/branching input, and execution of the generated ARM64 callback with a guest call and balanced stack.
- Input bring-up: fixed classic DirectInput keyboard/mouse enumeration and removed donor rescan writes to NFSU2 address 0x8364e8. Kernel probe failed before the change and passed afterward, including unchanged Most Wanted code bytes. Added tested Windows virtual-key/Unicode bridge and deterministic frame-based guest input.
- Ruling: Windows virtual-key conversion currently exposes a US-compatible layout. Native physical scan codes remain available; other Windows keyboard layout mappings are not verified.
- Ruling: Compile the large D3DX shard 47 at O0 during bring-up because Apple Clang's O2 pass stalled there. Other generated code uses O2. Split/reassess that CFG before making performance claims.
- Original main/career/Quick Race menus rendered; keyboard navigation and profile creation/reload verified. Native app packaging and folder selection implemented; app gameplay acceptance remains pending.
- Independent runtime review identified a D3DX export-name allocation leak, relative app-save path handling, incomplete page checks for long callback matching, donor-specific controller helpers, and right-modifier queries. Fixed all five; focused callback/app/keyboard checks pass. A 60-second headless workload reduced process-heap live bytes from 49.17 MB (2,678,688 allocations) to 1.56 MB (14,903 allocations).
- Profiling found CPU vertex-shader execution dominated menu time. Enabled the existing Metal vertex-shader path; real menu output retained and frame time fell substantially. Race rendering/visual parity still requires observation.
- Race loading reached bounded generated audio graphs over 4 KiB with forward min/max branches. Added native compilation tests for forward control flow, middle-page validation, and smaller templates near page boundaries. Capture remains offline; unknown targets terminate with diagnostics.
- Quick Race observed on the original track with car, opponents, HUD, countdown, throttle, steering, pause, restart, and return to a working menu. Engine run `out/boot-039-live.log` ended via guest `ExitProcess(0)` with zero unresolved targets, unsupported instructions, or unimplemented imports. Actual Metal screenshots are under `out/live8-screens`.
- Media acceptance: `out/media1.log` played the unskipped EA logo, safety clip, and complete 61.43-second attract movie. `out/media2.log` played the complete 50.58-second `storyfmv_rac01` opening story movie, then loaded `Scene_IntroNisDD_BundleB` and reached the career race. Frames and captured native PCM are under the matching `out/perf-media*`, `out/media*-screens`, and `out/audio-media*` paths. The attract movie's split-screen shots were checked against the original video and are intentional. This does not establish every story movie or full-career coverage.
- App verification: `out/Most Wanted.app` is signed ad hoc and contains an ARM64 executable. It opened its native Metal window, reloaded the profile, and reached Quick Race with the default Most Wanted save directory. The user confirmed the visible app reached its menu.
- Closure investigation: the user clarified they had closed the visible app themselves. A diagnostic run recorded the frontend quit path at block `0x005a4c87`, quit flag 1, and guest `ExitProcess(0)`. One- and sixty-second background/foreground tests also resumed successfully. Temporary quit-store instrumentation was removed; no spontaneous closure was reproduced. A prior SIGTERM-ended run is not counted as a completed stability test.
- Review follow-up: fixed process-exit ownership by making jump contexts thread-local, notifying host shutdown for worker exits, and disarming the main guest context on return. The native test executes the actual Win32 adapter on both owner and worker threads. Added an automation quit command through the normal lifecycle route.
- Verification: 22 Python checks, 620 ISA checks, native callback ABI and MSVCRT harnesses, kernel/input/timer checks, and the donor PS 2.0 texture-coordinate regression check pass. The final app acceptance run and package verification are recorded below.


## Final local acceptance

- Native app: `out/Most Wanted.app`; ARM64 Mach-O, ad hoc signature verified with `codesign --verify --deep --strict`. The final app executable SHA-256 is `c1ab6d96f5c231873e52892e02f6f2aa97aa88f4204a9233d62c48c8bede4550`.
- Actual Apple M1 Pro Metal rendering at 1280x960. The final single-instance run lasted 735.2 seconds, including a continuous race observed at 10:48.93 on the HUD. It included short throttle/steering checks and idle periods, not a completed lap. Pause, restart, return to Quick Race, and the normal lifecycle quit route worked afterward.
- `out/acceptance-last-run.log`: guest `ExitProcess(0)`, zero unresolved indirect targets, zero unsupported instructions, zero unimplemented imports, zero game-folder writes. No test instance remained running after shutdown.
- Race process-footprint observations: 442.20 MiB at 60 s, 444.99 at 120 s, 445.52 at 240 s, 459.66 at 360 s, 446.89 at 480 s, 446.24 at 600 s, and 458.08 at 680 s. The observed race range was 441.17-459.92 MiB, with loading peaks followed by decreases. This is sampled process footprint, not proof that every allocation path is leak-free. At normal exit, the process guest heap had 4 live blocks after 14,908 allocations and 14,904 frees, with a 1.57 MiB peak.
- Speaker output was muted during this quiet stability run while native CoreAudio mixing/cursors and PCM capture continued. The capture contains 734.74 seconds of stereo 44.1 kHz PCM. Earlier visible/engine runs opened the actual MacBook speakers with normal audio enabled. Menu/race music, engine/effect mixing, and the tested movie audio paths were exercised.
- Evidence: `out/acceptance-screens/nfsu2_frame_54203.png` (10:48.93 race), `nfsu2_frame_54958.png` (restart), and `nfsu2_frame_56291.png` (return to Quick Race). Matching per-second memory, guest/render timing, and GPU records are in `out/perf-acceptance`; native PCM is `out/audio-acceptance.s16`.
- Final checks: 22 Python tests; 620 ISA tests; native ABI, CRT, kernel/input/timer, and PS 2.0 coordinate harnesses passed. Logs are `out/tests-final.log` and `out/kernel-final.log`. Independent source review and follow-up checks found no remaining material issues in the reviewed scope after the fixes above.
- All work remains local. Backups and the donor project were preserved. No git commit, remote change, or publication was made.

## Limits of this milestone

The original menu and a playable race, plus the tested audio/video/cutscene paths, are established. Full-career progression, every car/track/movie, physical controllers, and non-US Windows virtual-key layouts have not been exhaustively tested. The build currently has 34 local native audio callback templates; a new shape stops for capture and an ARM64 rebuild. The original D3DX shard 47 remains compiled at O0. These limits must remain visible when describing the result as a local prototype.
