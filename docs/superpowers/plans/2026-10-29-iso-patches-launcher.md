# ISO patches and launcher implementation plan

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development for the task being implemented. Track evidence below.

**Goal:** Install from the new ISO backup and launch the native game at a chosen resolution with Standard, HQ visuals, or full HQ behavior.

**Architecture:** Extend the bounded disc reader and retain atomic installation staging. Decode official replacements natively, extract HQ components with a verified native extractor, and select isolated data/save profiles through the existing Cocoa app. Port Windows code hooks into the native runtime rather than loading x86 DLLs.

**Tech stack:** Python, Rust's standard library for RTPatch decoding, native Inno extraction, C/Objective-C, Metal.

**Spec:** `docs/superpowers/specs/2026-10-29-iso-patches-launcher-design.md`

## Constraints and review focus

- Preserve all original backups and existing saves; publish staged installations only after verification.
- Reject unsafe archive paths, symlinks, unknown executable hashes and invalid patch outputs.
- No Wine, Rosetta or runtime x86 interpreter.
- Use relative paths and generic identifiers in repository files.
- Test full HQ with added cars, shader variants and audio callbacks. Extraction alone is insufficient.
- Keep menu and mouse coordinates consistent at 4:3, 16:9 and 16:10.
- Movie framing must preserve the original content and clear borders.
- Missing HQ files or unimplemented hooks must produce an explicit unavailable state.

## Tasks

- [x] Add logical ISO reads, bounds checks and Joliet coverage in `tools/install_game.py` and `tests/test_install.py`.
- [x] Decode official 1.3 with `tools/official_patch.py`, a std-only Rust codec, and verified file hashes. Verify against the actual supplied archive.
- [x] Integrate ISO installation, WidescreenFix inputs and HQ extraction. Test complete fresh installation in an ignored directory.
- [x] Add Cocoa launcher mode/resolution persistence, installation validation and separate save paths. Test option validation and actual launcher behavior.
- [x] Reconstruct the original supported runtime image from the HQ code sections and official resources while preserving the official patched executable and selected game root.
- [x] Port widescreen projection, UI, movies and configured graphics behavior. Verify native hooks and real game captures at multiple resolutions.
- [x] Build distinct HQ visuals and full data trees with reproducible component choices. Enable each mode only after native validation succeeds.
- [x] Port required enabled HQ code mods, including expanded car support. Record exact coverage and unresolved features.
- [x] Verify Standard, HQ visuals and HQ full in menus, races, audio and movies; package the launcher and update README.

## Evidence

The new ISO reader passes plain and raw-sector cross-boundary reads, extent rejection and matching Joliet directory tests. All four supplied ISO payloads extracted with ZIP CRC checking (1406 files).

Official patch decoding verifies seven files by size, both RTPatch checksums and SHA-256. The protected official executable is `e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb`. HQ's unprotected executable is `8393f3487e3e024d6c2196d8adcd3f5b1b38077a893d9161a6f9ac61d587fa19`; its `.text`, `.rdata` and `.data` match the existing lifted target byte for byte.

The HQ executable modifies three shader resources. Using its resources with the original renderer produced invalid geometry. Combining its verified code sections with the official resources reconstructs the original supported image exactly: `80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c`. All 33 resource leaves match. Standard and HQ visuals use this image; the full renderer requires its own verified module initialization.

The fresh ISO installation has separate Standard, HQ visuals and HQ full trees. Native launcher tests exercise all three choices, resolution persistence, separate saves, missing files and unavailable modes. Full has an additional runtime capability gate that cannot be bypassed by changing installation metadata.

Native TexWizard maps 446 unique texture names and registers the supplied texture pack through the original resource loader. Four supplied non-power-of-two textures exposed incorrect source mip sizes in that loader. Focused tests now exercise corrected dimensions, guarded source reads and all actual mip payloads. COM and Metal support up to 16 mip levels.

The supplied HQ shader corpus translates and compiles against the expanded Metal backend. Tests cover vertex/pixel shader 3 interfaces, 16 samplers, volume textures, branching, derivatives, projected samples and exact L8 luminance replication. Unsupported instructions fail explicitly. Standard shader regression testing and live mode acceptance remain in progress.

The Python suite currently passes 77 tests with nine optional data or hardware checks skipped. Separate Metal runs pass all six shader/backend tests. These checks do not establish playable full HQ behavior.

Subsequent live Standard testing found an SM2 regression in the expanded backend: sampler declarations/bindings still stopped at stage 3. Support now covers all 16 SM2 samplers and eight texture coordinates, with a failing original shader and a stage-4/t7 render regression. The unskipped attract movie and title screen at 1920x1080 then passed with a normal exit and native PCM capture. A fresh career input script stopped at the career menu, so it does not establish story/race acceptance. A separate live 3D regression remains under investigation.

Full-only HD Content Support adaptations cover six known font hashes, all four cursor dimension loads and logical movie dimensions. Three tests execute the actual original instructions and verify that movie fitting happens once. Full-only MotionBlurController adaptations reproduce its four configured float operands and minimum speed; three tests cover real game multiplications, x87 precision, inactive behavior, INI defaults and invalid values. SpeedReflect's supplied Full car table contains 97 records with usage values 0, 1 and 2 only; its upstream augmentation selects usage 3/4, so the original eight streaming calls already match this preset. No extra loading is invented.

The staged X360Stuff AOT module passes its original CRT and complete initializer in isolated native probes. The real module loader verifies the input hash, relocates 3550 pointers, binds 124 imports and maintains per-thread static TLS. Captured patch phases have 100 guarded native game functions and 25 continuation entries. This remains experimental: actual Full rendering, later patch phases and other enabled plugins are not validated.

### Full HQ component coverage

| Component | Current native coverage | Remaining acceptance |
| --- | --- | --- |
| X360Stuff 4.1 | Staged AOT CRT, initializer, guarded game functions; all 18 effects parse and execute their technique/pass lifecycle in isolated tests | Actual Metal drawing and later patch phases |
| WidescreenFix | Projection, centered HUD, movie fitting/borders, rain sizing, shadow camera projection, high-spec audio fallback | Remaining configured graphics, camera and input behavior |
| MWFixes | Enabled stability and purecall routines ported; canonical instruction/stack tests pass | Full mode live verification |
| XboxRainDroplets | Original supplied CRT and initializer run as ARM64; required two-UV fixed-function Metal path is implemented and tested | Combined module execution and live rain rendering |
| ExtraOptions | Original CRT and initializer parse the real INI as ARM64; all 452 changed bytes captured, bounded CRT environment adapters verified | Callback and continuation integration, live gameplay |
| FEShadows 2.1 | Six enabled behaviors ported with canonical branch/call tests | Full mode live verification |
| HDContentSupport 2.0 | Native NPOT loader correction and seven logical font/cursor/movie dimension adaptations | Full mode live verification |
| HDReflections 2.0 | Enabled resolution, LOD, mirror detail, culling and pool behavior ported; 12 binary and canonical instruction tests pass | Metal occlusion query review and live reflection passes |
| HUDAdapter | Two package callbacks and three minimap operands ported; aspect and canonical stack tests pass | Full mode live verification |
| MotionBlurController 1.0.0.100 | Four scalar reads and minimum-speed field ported and tested | Full mode live verification |
| Unlimiter 3.3.0.1338 | Core native hooks plus staged original CRT/initializer with actual settings and rim brands; all 384 changed bytes captured | Original callback and continuation integration, live customization and cars |
| XenonEffects | Staged original CRT, delayed startup callback and initializer; 18 verified global configuration fields and all 36 changed bytes captured | Combined native particle callbacks and rendering |
| SpeedReflect 1.2 | Supplied preset has no usage-3/4 entries; original eight streaming calls match its behavior | Confirm unchanged loading during Full run |
| TexWizard | Configured ROCKPORT360 pack, 446 mappings and original resource loading; actual replacement cache hits observed | Full mode live verification |
| ZPatchMW | Enabled AI crash and stutter routines ported; canonical call/branch tests pass | Full mode live verification |

The corrected Standard GPU renderer completed a race at 1920x1080 and exited normally after 120 seconds. Its world, car and HUD were checked in captured frames. The five rejected legacy pixel programs now explicitly support their valid PHASE, TEXREG2AR and TEXREG2GB instructions; all 51 original pixel programs compile against Metal. The remaining HQ visual crash is variant-specific: an Audi A3 front-wheel model at LOD 1 is absent at the live material call even though its stock and HQ payloads pass isolated original decoding/registration/lookup. Added wheel diagnostics will capture the selected part and requested hash. Visual readiness remains disabled.

The first experimental Full startup stopped safely on a Win32 import cache bug: the ASI called QueryPerformanceCounter before the game, exposing a cache that assumed one module's import index. The captured images and CPU state are retained locally. This is not a successful Full rendering run.

The clock cache now passes the actual ASI CRT followed by alternating game, D3DX and ASI calls. The second Full startup completed the original initializer, created the device and started native audio, then exposed an X360Stuff patch that overwrites its own zero-quality audio branch target. A bounded short-jump repair is being validated against the original audio selector; it preserves the intended 48 kHz path and the configured high-spec fallback.

Native static branch hooks have explicit source/target declarations. Generation validates instruction boundaries within each decoded body, splits x87 regions, retains arithmetic flags in affected functions and refuses unsupported register-local optimization. Invalid declarations abort generation instead of producing Standard trap stubs. Six tests cover these properties, including the real generator error path; the feature passed independent review.

The Metal backend now has scoped predefined state blocks and depth bias support, with eight isolated tests and sanitizer checks passing. Slope bias uses Metal's rasterizer; normalized constant bias uses a lazy fragment-depth variant so its units match Direct3D rather than Metal's depth-dependent units. Standard and HQ pixel programs compile in that variant. Independent review and a combined live build are pending.


### Subsequent live validation

Standard completed the unskipped opening story movie, following in-engine IntroNisDD scene and career race at 1600x1000, then exited normally after 180 seconds. Native PCM output was captured. The optional IntroNisDD rev-data file is absent from every original disc payload; all 29 supplied rev-data files match the installed Standard and Visual copies.

The Visual wheel crash was caused by stale stock preload caches. Their stock WHEELS offsets pointed into unrelated HQ data or beyond its end. The builder now writes supported zero-entry headers to the existing preload caches, allowing the original loader to read the selected HQ files normally. Independent review verified the original cache lookup and disk fallback. Standard gameplay, car tables, audio, movies and shader files remain intact.

Visual completed normal 120-second race runs at 1920x1080 and 1600x1000, then a final production-binary run at 1280x960. Captured garage, race and final frames have textured cars, world and HUD with no prior wheel failures. A further 180-second production run at 1920x1200 completed the full story movie, in-engine cutscene and career race. PCM capture remained active. Visual readiness is enabled in the builder and installed manifests. The packaged launcher offers Standard and Visual; Full remains gated.

The coherent Rain backend build passed 119 Python tests with 13 optional checks skipped. Subsequent targeted checks include the new physical device-resolution getter, Visual readiness, and reflection instruction tests. The visible Cocoa launcher test passes with isolated preferences; it uses its modal window rather than assuming activation has made it key within half a second.

Experimental Full6 completed 240 seconds with all observed X360 startup, delayed-render and late phases captured and compiled, reaching an in-engine scene with native PCM output. No unresolved imports/calls, executed unsupported instructions or Metal errors were reported. This does not establish all plugin behavior or arbitrary self-modifying code coverage. Aspect auditing found the X360 renderer still held a logical 4:3 aspect at a 1920x1080 device size; a bounded physical-resolution adapter is being tested. Full readiness remains disabled.

Unlimiter's original initializer applies 384 changed bytes across 79 spans; its naked push/RET caves require explicit continuation routing. Extra Options applies 452 bytes across 80 spans after reading the actual 14,471-byte INI. Its three bounded CRT control/status helpers pass 1,536 precision, rounding and exception-mask roundtrips plus six status cases. XenonEffects installs its original delayed startup callback before reading configuration and initializing its nine active redirects. These isolated probes do not count as gameplay acceptance.

### Reproducible preparation and combined startup

The tracked module preparer verifies all six input modules before generation and keeps original binaries and derived C in ignored folders. Pinned address metadata reproduces the tested 577-entry X360Stuff function table. Import cleanup, static TLS and entrypoint metadata are verified against each input image.

Game generation now records input, option, tool and output hashes. Captured-phase routing verifies that provenance before replacing any managed output. Synthetic native tests cover preserved Standard bodies, all-phase continuation closure, x87 precision, unknown signatures, incomplete decoding and failed preparation leaving existing output intact. Full remains disabled.

The original Rain, Unlimiter, game and X360Stuff startup initializers run together in a bounded ARM64 probe that stops before creating a game thread or device. Later Unlimiter code writes require an accepted operand tuple before the writer returns. A new tuple must be captured and compiled before execution continues.

The gamma/AA Metal backend passes focused GPU tests. Standard and Visual each completed 120 seconds of movies and in-engine scenes with normal exit. A separate 240-second Standard run reached a player-controlled race and captured native PCM with no reported starvation. The current Python suite passes 180 tests, with 15 optional checks skipped.

### Requested follow-up after patch integration

Provide one build entry script accepting an extracted installation, ISO images, or BIN/CUE images. Extract disc inputs, verify supported game checksums, fetch pinned patches from their original sources into an ignored local cache, and produce the macOS app. Keep downloaded patches, game files and generated game code out of the repository.

Rewrite the README for someone building from their own game copy. State the ownership requirement and absence of bundled game assets, accepted game editions/versions, prerequisites, one build command, launcher modes, implemented features and patch versions. Put the technical explanation of ahead-of-time CPU translation, native platform services and Metal rendering at the bottom. Describe actual limitations and keep Full unavailable until its complete selected mod behavior passes acceptance.

### Production all-module integration

The tracked production build now links the original X360Stuff, XboxRainDroplets,
Unlimiter, ExtraOptions and XenonEffects modules, alongside D3DX, through the same
verified catalog. All five original ASI CRTs and immediate initializers pass a
bounded headless probe. The original game CRT then schedules X360 initialization
in its actual order; a separate bounded call verifies the original delayed Xenon
wrapper, selected configuration and initializer. These probes create no game
window or device.

Combined captures generate 250 guarded native game functions and 101 additional
continuations without unsupported instructions in those bodies. ExtraOptions has
eight explicitly guarded runtime write fields. Its actual callback produces all
eight heat/headlights/freeze combinations, and its PageUp arithmetic cycles
through heat levels 1 through 10 and wraps. The keyboard bridge now supplies the
pressed-since-query bit required by those original callbacks. The native WS
settings fallback supplies its verified missing defaults while preserving saved
values.

The latest Python suite ran 277 tests: 255 passed and 22 optional checks skipped.
Full remains unavailable in the launcher until the combined live rendering,
driving, media and added-car acceptance checks pass. Earlier three-ASI live runs
do not establish those all-module results.

### Full renderer corrections

The GPU vertex cache now keys programs by their normalized declaration contents,
rather than transient guest declaration handles. The original fullscreen helper
creates a new declaration on each draw; its repeated handles exhausted the old
cache and forced scene draws onto the CPU path. The corrected combined run has
an upright frontend and a measured menu window with median 16.666 ms frames.
This is menu evidence only, not a driven-race performance result.

Recorded StateBlocks now own their float, integer and boolean constant payloads.
Apply no longer rereads a guest pointer that the original effect code has reused;
Capture refreshes the recorded ranges from the current device state. Focused
native and sanitizer checks cover all six vertex/pixel constant types.

The selected HDR shader writes two different outputs: luminance and an HDR mask.
Its original effect binds two 320x180 A8R8G8B8 targets. Both COM bindings, queued
Metal attachments and independent shader outputs are now preserved, including
per-target color masks, ordered clears, format-aware pipelines and depth-bias
wrappers. Real Metal readback verifies the original HDR shader's two numerical
outputs. All 51 Standard pixel shaders and 166 HQ programs pass compilation and
their applicable depth variants; 165 of the 166 HQ translations remain unchanged.
Screen MRT transitions also resolve prior MSAA contents before single-sample use.
Live exposure, driving and added-car acceptance remain pending.

The last pre-MRT combined run exited normally after 360 seconds with 17,699 Metal
frames and no unresolved calls, unsupported instructions, unimplemented APIs or
audio starvation. Its race and media assets loaded, but its timed race expired
before player input, so it does not establish driving acceptance. Two additional
bounded audio callback templates now execute in the actual game; all 37 observed
templates remain generated locally from the user's files.

### Complete audio preparation and ordered HDR readback

The audio preparer validates all 301 supplied ABKC banks using their module and
relocation metadata. Their 386 constructors produce 75 native templates; Standard
and Full have identical template sets. All 40 canonical helper destinations have
native function entries. All 75 bodies pass native execution at two relocated
bases with modeled callees, plus sanitizer checks. Preparation pins its generation
settings, rejects malformed or unsupported bodies, and rechecks its inputs and
managed output before publication. Generated bytes and sources remain local.

The combined 75-template Full run reaches a race and accelerates to 38 MPH, moves
away from the starting booth, pauses, and exits normally. It reports no unresolved
calls, unsupported instructions, unimplemented APIs or audio starvation. Short
steering transitions were obscured by diagnostic texture dumps; the next control
check will use lightweight captures. Frontend loading/rendering of CZ28 is a
confirmed added-car result: its record is appended at index 89 in the 97-car table.
Driving an appended car and restart/return remain open.

The remaining exposure error has a measured cause. The original X360 luminance
routine draws a lockable 113x64 A8R8G8B8 surface and immediately reads its pixels
within the same frame. The old backend returned an empty CPU buffer. Replaying
the original adaptation code reproduces the captured exposure 4.62428 from black
pixels; uniform byte value 64 produces exposure 1.11121 instead.

Metal now submits preceding draws as ordered partial chunks, copies the surface
to shared staging memory, and waits for completion before returning its pixels.
Partial chunks retain the drawable, color contents, depth and postprocessing
state. Only final Present advances frame counters and displays the frame. COM
propagates readback failure and preserves READONLY locks without uploading their
buffers. Real GPU tests cover tight and padded pitches, repeated draws/reads,
queries across chunks, 4x MSAA color/depth continuation, and failure/quit wakeups.
Live exposure and the remaining Full control checks are still pending.

### Full driving, added cars and remaining graphics checks

The ordered readback build completed a 603-second Full session at 1920x1080.
Captured final frames have readable sky, road, bridge and car exposure. A driven
Gallardo reached 67 MPH, with separate left and right steering, barrier impacts,
route progress and pause. The run exited normally with 16,911 Presents and no
reported unresolved calls, unsupported instructions, unimplemented APIs, GPU
errors, dropped frames or audio starvation.

A separate 741-second Full session at 1024x768 selected the appended SC300
(car-table record 95) through the original Stock selection menu. It drove,
steered, paused, restarted through the confirmation dialog, drove again, and
returned to the Quick Race menu. The run exited normally with 37,551 Presents
and the same zero-error checks. A measured active-driving window averaged
30.7 FPS. Both runs captured native PCM while speaker output was muted; these
captures do not establish subjective audio fidelity.

The remaining black water region was traced to overlapping pixel shader IDs:
the early shader 2 cube variant occupied the later shader 258 base slot. Native
base, cube and Enhanced reflection IDs now have disjoint ranges. Real Metal
tests verify separate shader functions and pixels, actual cube selection, the
highest supported pipeline keys, and refusal at base-ID exhaustion. Reinstating
the old offset reproduces the collision. In-game water verification is pending.

Full's selected depth of field and depth-masked motion blur require an INTZ
depth texture. The old COM path returned success with backend texture ID zero,
so those effects sampled a fallback image. Texture/surface aliases now reserve
one depth ID and own one shader-readable Depth32Float image. Focused CPU and
GPU checks cover the shared image, explicit depth writes and sampling, 4x MSAA
resolve, invalid inputs, allocation failure, release and Reset. Final combined
regressions and live Full movie, cutscene and graphics acceptance remain open.

The requested single build entry script and final README rewrite have not yet
been implemented. Download source and checksum research is local preparation,
not evidence that a fresh checkout can reproduce the current Full build.

### Final integration status

The component table above records intermediate development checkpoints. All
listed native integrations are now linked into the public build. Full20
verified the appended SC300 with driving, steering, pause, restart and return.
Full21 verified the unskipped story movie, following NIS and career race, with
real INTZ sampling. Full26 verified the public-derived native closure through
race, restart and normal return with no unknown patch/checkpoint, unresolved
call, unsupported instruction or GPU error. Its selected manual Drag event
does not establish moving-car coverage for the new closure.

The public pipeline derives 250 guarded game functions and 101 continuations
from the supplied files, without private captures or prebuilt game code. The
single-entry build packages a signed ARM64 0.3.0 app with its verified game
copy and enables Standard, HQ visuals and Full HQ in the launcher. The complete
fresh build and actual ISO/BIN-CUE source checks passed. The README describes
the supported edition, patches, own-copy requirement, translation model and
remaining visual/test limits. Unobscured live water remains a documented
coverage gap after the tested shader namespace fix.

The final signed 0.3.0 app also passed a moving-car check with its actual bundled
Full assets at 1280x720: automatic IS300, 48 MPH in gear 2, opposite steering
changes, normal exit and zero runtime/GPU errors or game-folder writes. This
closes the public-closure driving item left open by Full26. Its signature and
executable identity remained intact after play. Full28 cold startup took about
93 seconds and the clean active segment ran at 20.82 FPS; this is an experimental
port, not a completed performance or all-career certification.
