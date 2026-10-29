# Public app builder implementation plan

> Use the executing-plans workflow for implementation and reuse the existing
> focused reviewers. Do not publish or create additional commits without a user
> request.

**Goal:** Build the macOS app with one command from the user's supported game
copy, without including game code, assets or patch payloads in the repository.

**Architecture:** A small shell entry point prepares the local Python environment
and calls the Python pipeline. The pipeline stages and verifies game inputs,
downloads pinned patch payloads, applies existing native extraction/preparation
tools, generates the game and mod code locally, builds ARM64, and packages the
launcher. Existing managed caches can be reused only after provenance checks.

**Tech stack:** Existing shell, Python standard library, Capstone/pefile, C,
Objective-C, Metal, native cabinet/Inno extraction and the Rust patch decoder.

**Spec:** The requested follow-up in the ISO patches plan and the user's builder
requirements. The user requested continuation and already chose the verified
NFSPlanet mirror when the EA endpoint was unavailable.

## Constraints

- One documented command accepts an extracted game folder, an image folder, or
  explicit ISO/BIN/CUE files. Preserve every source file and existing save.
- Support the pinned USA English Black Edition four-disc payload, unpatched or
  officially patched to 1.3. Identify disc roles from contents, not filenames.
- Check every required extracted game file by size and SHA-256. Check optional
  known binary inputs when present. Reject modified or incomplete required data.
- Download official 1.3, WidescreenFix and MW HQ from pinned verified sources;
  use Microsoft's redistributable only when the required DLL is unavailable.
- Downloaded installers are decoded by native tools and are never executed.
- All original/generated game or mod code, assets, caches and logs remain under
  ignored local output directories. Tracked checksum/address metadata is allowed.
- Full preparation must run reproducibly from the user's files. Private captures,
  private probe scripts and prebuilt generated game code are not build inputs.
- README leads with the user's own-copy requirement and one build command. List
  accepted versions, patches, features and observed limits; technical translation
  details belong at the bottom.

## Review focus

- Unordered images, duplicate disc roles and a CUE referring to an escaping path.
- Case or file/directory collisions, symlinks, corrupted ZIP payloads and an
  extracted installation that has partial or incompatible modifications.
- Interrupted or substituted patch downloads and a cached file whose name
  matches but whose complete digest does not.
- A failed preparation must preserve the last usable installation and app.
- A fresh checkout must derive every required HQ phase without private outputs.

## Tasks

- [x] `tools/patch_sources.py`, `tests/test_patch_sources.py`: implement
  `fetch_patch(key, cache=Path('out/downloads')) -> Path` for official-1.3,
  widescreen, mw-hq and directx. Test streamed size/hash checks, cache verification,
  temporary cleanup, atomic replacement and fresh publisher mirror discovery.
- [x] `tools/game_sources.py`, checksum metadata and `tests/test_game_sources.py`:
  implement `stage_game(sources, destination) -> dict`. Reuse `RawISO` and safe ZIP
  extraction, validate bounded single-track CUE files, identify all four ZIP
  roles and verify the resulting payload. Test all input forms with small
  synthetic discs and profiles; verify actual source checksums separately.
- [x] Update `tools/install_game.py` and `tools/official_patch.py` to accept
  explicit verified patch paths, direct official EXE input and the shared staged
  payload. Keep the final installation publication atomic and validate all
  binary/image and variant outputs. Run existing installer/patch regressions.
- [x] Replace the private Full phase-preparation recipe with public headless
  native preparation. Run original CRT/startup/render initializers in bounded
  preparation phases, derive all finite guarded runtime writes and rebuild only
  after verified captures. Test unknown states and failed publication, then
  reproduce the current route/checkpoint set from fresh managed output.
- [x] Add the shell entry point and Python orchestration. Validate prerequisites,
  prepare dependencies locally, fetch/verify/stage inputs, generate callbacks and
  native code, build and package. Test argument routing and failure preservation;
  exercise actual ISO, extracted-folder and raw BIN/CUE source validation.
- [x] Rewrite README and run repository privacy/game-content checks, focused
  tests, actual Metal checks and a fresh end-to-end app build. Verify the final
  launcher offers resolution and the three requested modes with isolated saves.

## Execution notes

The implementation languages and staged pipeline are implementation choices,
using the existing project tools. No extra user-facing configuration is needed.
Full21 live acceptance owns the GPU and a frozen engine/source pin; builder tools
can progress independently, but runtime preparation changes wait until it exits.

Progress: public entry and offline audio verification tests pass. Headless Full
preparation is wired into the build and awaits fresh native integration proof.
The pipeline derives routes from the public module/checkpoint metadata and
finite native execution. Failed build logs remain under ignored out/.

Public preparation proof: out/public-native-build2/manifest.json records native
module initialization, complete runtime preparation and a final repeat run, all
exit 0. Generated closure: 250 guarded functions, 101 continuations, 1,791
changed bytes, 1,801 guarded bytes and zero translation traps. No private
capture or probe is a build input. Actual four-ISO installation verified 1,411
source files; actual BIN/CUE staging passed all 16 source tests.

Ruling: Full HQ is enabled in builds containing the native modules after the
completed added-car, driving, restart, media and depth-buffer acceptance. The
water shader namespace fix has actual GPU and mutation tests; unobscured live
water remains a documented validation gap rather than an indefinite launcher
gate. Full-career and every-track coverage are also explicitly unverified.

The first broad run found a timestamp-dependent synthetic ZIP fixture. A
controlled four-second timestamp difference reproduced the checksum failure;
fixed ZipInfo timestamps make the same reproduction pass. The broad suite is
being rerun. The documented single entry is undergoing a complete ISO-to-app
acceptance build, using fresh extractor source and newly staged game data.

The documented entry `./build.sh game_backup2` completed the full fresh
ISO-to-app build and packaged version 0.3.0. The resulting executable is ARM64,
uses only macOS system libraries/frameworks and passed deep strict signature
verification. All three mode manifests are ready. Final application identity
is recorded in out/final-app-identity.json. The corrected broad suite ran 342
tests successfully with 28 hardware/private-input skips. Visible Cocoa testing
selected all three modes, persisted 1920x1080 and used Play successfully. A
separate own-window capture confirms actual native control rendering.

Read-only final integration review has no unresolved findings. Full26 ran the
public-generated engine through race, standings, restart, pause and return to
the menu without unknown routes or GPU errors. Moving-car confirmation on the
final signed app remains the final focused acceptance step.

Final signed-app acceptance completed using the actual bundled Full data at
1280x720. The automatic IS300 reached 48 MPH in gear 2; opposite steering
inputs changed heading and position. Full28 exited normally after 347.845
seconds with zero route/runtime/GPU errors, dropped frames, audio starvation,
cursor overruns, texture failures or game-folder writes. Its 11,427 Present
calls and 11,426 Metal submissions include one pending shutdown frame. The
signed executable hash remained unchanged and deep strict codesign verification
passed again after the run. Actual screenshots confirm Auto selection and the
moving race. A final source scan found no supplied personal identities, home
paths, binary assets or Unicode dashes in repository source files.

All requested implementation tasks are complete locally. Remaining coverage
limits are documented: unobscured live water, complete Career/every-track and
controller coverage, and Full HQ performance. No additional commit or external
publication was requested or performed.
