# Most Wanted native Apple Silicon port

Status: approved by the user on 2026-10-28. Research completed; implementation in progress.

## Outcome

Run the supplied Windows PC version of Need for Speed: Most Wanted (2005) as a native ARM64 macOS application, using the approach in the sibling NFSU2 project. The first usable milestone is the original game's interactive menu and a playable race. The user confirmed that an asset viewer does not satisfy this milestone.

Translate the original x86 machine code ahead of time to C, compile that C to ARM64, and supply the Windows and DirectX interfaces through a native runtime. Translate Direct3D 9 drawing and shaders to Metal directly. A release that requires Wine, CrossOver, Rosetta, an x86 interpreter, or a browser does not meet the goal.

## Measured inputs

The workspace initially contains only `game_backup/`, with four MODE1/2352 BIN/CUE disc images and an update ZIP. Research read these inputs without changing them or executing any Windows program.

| Input | Observed property |
| --- | --- |
| Disc volumes | `NFSMW_DISC1` through `NFSMW_DISC4` |
| Game archives | One ZIP per disc; 6, 10, 83, and 1,307 entries respectively |
| Game data | Archive directories include CARS, TRACKS, GLOBAL, FRONTEND, SOUND, MOVIES, LANGUAGES, NIS, and MEMCARD |
| Available patched executable | `speed.exe`, 6,029,312 bytes, inside the update ZIP |
| Executable SHA-256 | `80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c` |
| Executable format | PE32 i386, image base `0x00400000`, entry `0x007c4040` |
| Executable image extent | `0x00400000` through `0x00a78e4e` exclusive, before host page rounding |
| Executable code | `.text` at `0x00401000`, 4,776,613 virtual bytes |
| Imports | 300 entries across 14 DLLs |
| Hidden relocation section | Whitespace-named section at `0x00a38000` |
| Recovered relocation data | 1,271 blocks; 114,755 HIGHLOW slots; every slot contains an in-image address |
| Relocation code references | 31,648 pointers into `.text`, covering 21,913 distinct target addresses |
| External effect dependency | `d3dx9_26.dll`, including effect creation and matrix/vector operations |

The distinct relocation targets are discovery seeds, not a measured function count or proof of complete code coverage. The four archives' directory tables were read successfully; full extraction and CRC verification remain implementation work. The disc-1 root executable is a different 7,250,800-byte file and is not the selected translation input.

The x86 DirectX cabinet on disc 1 contains the required D3DX DLL. The x64 cabinet contains another DLL with the same filename, so extraction must select by architecture and fingerprint, not basename alone.

| D3DX property | Value |
| --- | --- |
| File size | 2,297,552 bytes |
| SHA-256 | `8ea96fe01c3c86a36fcb3795ae03eb12034003e335ef475571efaeda17c5bc78` |
| Machine | i386 |
| Preferred base | `0x00400000`, requiring relocation beside the game |
| Image size | `0x0024a000` |
| Entry RVA | `0x001fff6c` |
| HIGHLOW relocations | 27,609 |
| Required exports present | All 13 imported by `speed.exe` |
| Imported dependencies | 63 MSVCRT, 27 GDI32, 72 KERNEL32, and 3 ADVAPI32 entries |

## Existing work and choice of approach

The sibling `../NFSU2/NFSU2Recomp` has an x86 lifter, a guest memory model, Windows/COM adapters, a Direct3D 9 to Metal backend, native audio/input, build scripts, diagnostics, and a Swift launcher. Its HEAD during research was `b881f30`; it also has uncommitted changes. Treat it as a source reference and leave it untouched. If files are reused, take a local snapshot into this workspace and record per-file hashes and the donor revision, so later NFSU2 edits cannot change this build silently.

The donor's LICENSE allows personal local modification and restricts redistribution. Preserve its notices in any copied material. This work stays local; publication is outside this request and requires separate review and the user's confirmation.

Three routes were considered:

1. Adapt the PC static recompiler and native Metal runtime from NFSU2. This matches the supplied game, requested architecture, and existing working reference. Selected.
2. Start from an Xbox 360 recompilation. [Speedbreaker](https://github.com/SpeedBreakerProject/speedbreaker) supports Apple Silicon but requires Xbox 360 code/assets and uses MoltenVK. It does not accept these PC discs, so it does not solve this task.
3. Rebuild from a complete source decompilation. [The existing decompilation](https://github.com/dbalatoni13/nfsmw) includes a PC v1.3 target but describes itself as work in progress. Use compatible published research as a reference; do not assume it supplies a finished native PC port.

## Runtime boundaries

Reuse the proven compiler/runtime mechanisms where they apply. Keep game-specific knowledge in a Most Wanted target description and small adapters. Do not copy the entire NFSU2 application and relabel it.

The target description records executable/DLL fingerprints, image and code ranges, entry points, discovered function seeds, import calling conventions, and verified hooks. Reject a different executable or DLL before loading or translating it. Never silently accept a binary by filename or size alone.

The donor has hardcoded addresses in its dispatch range, heap image classification, boot harness, overrides, diagnostics, compiler return handling, and renderer integrations. Audit these before reuse. In particular:

- Its `server.dll` load base, `0x00a00000`, overlaps Most Wanted's image. Assign any lifted DLL an explicitly checked, non-overlapping range.
- The lifter loads NFSU2-specific return behavior from `tools/retpast.txt` and has an address-specific optional float-conversion optimization. Replace these with target-specific inputs; numerical addresses alone must not enable behavior in another game or module.
- NFSU2's D3DX optimizations hook its statically linked effect code. Most Wanted imports a separate D3DX DLL. Leave those hooks out until matching Most Wanted/DLL behavior has been established.
- Renderer, audio, timing, network, and widescreen integrations can call game functions or inspect game data. Keep only the parts backed by verified Most Wanted interfaces.

Translate `speed.exe` and the supplied x86 `d3dx9_26.dll` into separate generated modules, with unique symbol prefixes, import tables, and function lookup ranges. Map the original DLL bytes at the same fixed guest base used for its translation, apply its relocations, bind imports, and run the required DLL initialization. Resolve the game's static D3DX imports through that module. The builder chooses the actual DLL range after checking every reserved guest region.

Implement the MSVCRT calls reached by the D3DX effect path using guest-aware adapters. Guest pointers, x87 results, callback functions, variadic calls, exception handling, allocator ownership, and stack cleanup must follow the Windows x86 ABI. A host function pointer cannot stand in for a guest callback or COM vtable entry. Report an unsupported reached operation clearly; returning success without doing it does not establish compatibility. Unused font/compiler exports do not need implementation for this milestone.

Keep a 32-bit guest address space backed by host memory, as in NFSU2. Guest executable instructions run as precompiled ARM64 functions; PE bytes remain available for constants, resources, vtables, and data. Report unresolved control-flow targets with module and guest address. Discover additional reachable code as needed, regenerate, and keep the rebuilt path reproducible.

The native COM adapter supplies the D3D9 device and resources that lifted D3DX expects. Reuse the existing Metal command submission and shader translation where compatible. Verify Most Wanted's actual shader versions, vertex declarations, render targets, depth/stencil operations, and effect states; those have not been measured yet. Start with the original visual behavior before considering HD rendering features.

## Data, controls, audio, and application

Extract the four discs into an ignored local game-data directory. Read raw MODE1 sectors correctly, preserve long filenames and Windows archive separators, reject paths that escape the destination, and check archive CRCs. Copy the selected executable from the update ZIP and the fingerprinted x86 D3DX DLL from the disc cabinet. Do not run an installer, patcher, key generator, or other bundled executable. Preserve the original backups.

Adapt case-insensitive Windows file lookup and redirect writes to a separate Most Wanted save/registry area. Do not reuse NFSU2 save paths. Verification runs use isolated save and registry directories. The application must create, persist, and reload its own game profile without writing into the backup or the NFSU2 project.

Provide keyboard steering, throttle/brake, menu navigation, pause, restart, and quit. Retain native GameController support if the donor adapter can be reused without game-specific assumptions; physical-controller verification is separate from keyboard acceptance. Supply native audio with working menu/race playback and volume/pause behavior. The milestone also requires original movies, cutscenes, music, and sound effects, as clarified by the user. Custom music, multiplayer, cloud sync, HD effects, and ASI mods remain subsequent work.

Package a local `.app` that can select the extracted game folder and start the native engine. Reuse the donor's Swift/AppKit patterns after the engine path is demonstrated. Do not derive player identity from the macOS account. A missing or unsupported game folder must produce a useful error.

These implementation choices are proposed defaults, not extra requirements claimed to have been supplied by the user: C/Objective-C runtime, Python translation tools, Swift/AppKit launcher patterns, offline first, and original rendering first. Use installed dependencies where sufficient. Do not add a general-purpose emulation framework or replace the native Metal renderer.

## Evidence required for the milestone

Scope update from the user: sound effects, music, videos, and cutscenes must work too. They are required acceptance work for this milestone. Verify original intro and story videos, in-engine scenes, menu/race music, and race effects; do not skip them to claim completion.

Completion requires an observed run of this game's code, not just successful compilation or a Metal test window:

1. A repeatable build from the extracted, fingerprinted PC binaries produces an ARM64 Mach-O engine and local `.app`.
2. The original main menu renders through Metal and responds to keyboard navigation.
3. A player can select and start a Quick Race, see the car/road/HUD, steer and accelerate, pause, restart or finish, and return to a working menu.
4. A race session lasts at least ten minutes without an unsupported instruction, unresolved dispatch, unimplemented reached import, crash, or steadily growing committed memory. Record sampled memory observations rather than claiming that this proves the absence of leaks.
5. Race and menu audio work, and quitting releases the application cleanly.
6. A profile/save survives an application restart, with writes confined to the intended save area.

Record build commands, selected input hashes, native architecture, screenshots of actual menu/race frames, and the matching logs. Use Metal validation while investigating rendering defects. Add focused checks for new parser/relocation/ABI logic and retain applicable donor ISA, heap, and shader tests. Compare x86/x87/ABI behavior against an available trusted reference where practical; do not claim differential verification that was not run.

Screenshot capture and repeatable automation must be implemented or adapted for Most Wanted. NFSU2's menu scripts and game-memory probes are not acceptance evidence for this game. A test triangle or black-window Present counter is useful bring-up evidence but does not meet the menu/race requirement.

## Work order and open engineering risks

After approval, write the implementation plan around these checkpoints:

- Establish a reproducible local input extraction, fingerprint report, donor snapshot, and code/relocation discovery pipeline.
- Compile and exercise the game entry/CRT and the relocated D3DX module with traced imports and callbacks. Resolve ABI and image-layout failures before layering game patches over them.
- Bring up real device/effect creation, then original menu rendering and input.
- Reach Quick Race, resolve gameplay/audio/rendering failures, and verify the acceptance run.
- Package the working engine and repeat the run through the `.app`.

Research has established usable input binaries and pointer maps. It has not established lift coverage, correct D3DX/CRT execution, complete Windows API compatibility, shader compatibility, or a working game frame. The external D3DX/CRT integration and unidentified game-specific runtime assumptions are the first engineering risks. Neither a completion date nor a frame-rate target is supported by current measurements.

Public technical research that may help identify engine structures: [nfsmw-2005-re](https://github.com/s-b-repo/nfsmw-2005-re). Check any imported material's exact version and notices. Do not treat published addresses as valid for this executable until matched against its bytes.

## Approval boundary

The user approved implementation with "go" and subsequently required sound, music, videos, and cutscenes. Local implementation, builds, and game verification are authorized. No publication or external posting is part of that approval.
