# Fullscreen Reliability and Port Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make normal fullscreen startup reliable, then target sustained 60 FPS at 1920x1080 in HQ visuals mode on an M1 Pro without losing game or mod behavior.

**Architecture:** Keep the native ARM64 runtime, AppKit window and Metal renderer. First distinguish game rendering from WindowServer presentation and fix the demonstrated failure. Then optimize the measured critical path, comparing the same race, settings and build conditions before and after each change.

**Tech Stack:** C, Objective-C, AppKit, Metal, Python standard library and the existing unittest suite.

**Spec:** `docs/superpowers/specs/2026-10-28-native-metal-design.md`, supplemented by the user's requested order: fullscreen bugfix first, port performance second.

## Status

Fullscreen startup: **resolved**, accepted by the user on 2026-10-30.

The launcher now restarts the executable with the selected game path before engine initialization, so fullscreen starts with fresh AppKit state. Direct startup and the real launcher handoff showed visible game output, and the user confirmed loading completed. Version 0.3.5 is installed in Applications with the original game icon. The bundled restart regression and full suite pass (351 tests, 32 skipped).

The user stopped the repeated startup matrix after eight recorded attempts. The first attempt had no game-window observation and is inconclusive. Later attempts recorded visible windows across Standard, HQ visuals and Full HQ, including 720p, 1080p and 4K. No further startup matrix is required. Performance work remains pending; no speedup or 60 FPS result has been established.

## Global Constraints

- The user approved local execution on 2026-10-30. Publication requires separate authorization.
- Preserve native Apple Silicon execution and Metal rendering.
- Preserve sound, music, videos, cutscenes, input, saves and all advertised Full HQ behavior.
- Keep game assets, generated game code, profiles, screenshots, traces and executable files outside version control.
- Use isolated test profiles. Do not overwrite user saves, terminate user play sessions or clear system caches.
- Use repository-relative paths and ASCII punctuation in tracked documentation.
- Do not publish without the user's explicit authorization after showing the exact proposed public content.
- Agreed performance priority: sustained 60 FPS at 1920x1080 in HQ visuals mode first. Standard is a diagnostic comparison. Full HQ optimization follows; its target will be assessed from measurements. These are targets, not measured capabilities or promises.
- Keep 4K in correctness checks; do not make 4K Full HQ a performance acceptance target for this hardware.
- Keep requested features enabled during optimization comparisons. Lower-quality presets are separate comparisons, not evidence of a faster port.

## Review Focus

1. A Metal drawable can report presentation while the fullscreen window looks black. Acceptance must inspect the actual game window.
2. Activating the app, switching Spaces or toggling fullscreen can repair the symptom. Observe startup before taking any such action.
3. Launcher render resolution overrides the legacy in-game value. Benchmarks must record actual Metal dimensions.
4. Full HQ exposure reads pixels synchronously. Optimizations must preserve readback ordering and visible exposure.
5. Profiling, background pausing, cache warming and different race locations can distort comparisons. Record and control them.

## Tasks 1 and 2: Fullscreen startup - resolved

- [x] Distinguish valid GPU-rendered content from the black physical display.
- [x] Compare the working NFSU2 startup and isolate reuse of the launcher process image.
- [x] Add a failing bundled-executable regression, then restart into the engine while preserving mode, resolution, paths and saves.
- [x] Run the full suite and obtain an independent code review.
- [x] Package and install version 0.3.5; confirm visible output with the user.
- [x] Stop repeated startup testing at the user's request and mark the bug resolved.

## Task 3: Capture a repeatable race baseline

**Files:** Use `runtime/automation.c`, `tools/control.py`, `runtime/perflog.c`, `runtime/perflog.h`, `runtime/com.c` and `runtime/metal.m`. Extend timing capture only when existing records cannot explain the stalls.

**Interfaces:** Reuse `NFSMW_SAVEDIR`, `NFSMW_COMMANDS` and `PERFLOG`. Retain raw timings and captures under ignored output directories.

- [ ] Freeze one car, race, route, camera, opponents, graphics settings and input sequence. Record equivalent setup separately for modes with separate save formats or profiles.
- [ ] First capture HQ visuals at 1920x1080, then the same setup at 1280x720 and Standard mode at both resolutions as diagnostic comparisons. Use two-minute active-driving segments and three repetitions per configuration. Separate loading, menus, video and pause from the scored segment. Capture the Full HQ baseline after the primary workload is characterized.
- [ ] Record build identity, actual drawable dimensions, graphics settings, power mode, display refresh, thermal state and cache conditions. Do not run concurrent builds or game instances during measurements.
- [ ] Report average FPS; median, p95 and p99 frame times; frames exceeding 33.3 and 50 ms; guest CPU time; main-thread encode time; GPU time; waits; draw counts; compilation events and memory growth.
- [ ] Use sampling to identify slow functions, then confirm timings with profiling disabled. Quantify instrumentation overhead rather than treating profiled FPS as the final result.
- [ ] Rank measured costs: translated game code/dispatch, render-state and draw submission, GPU work, synchronous readback/query waits, compilation and texture streaming. Treat these as candidates until measured.

**Deliverable:** A baseline and ranked bottlenecks. Do not prioritize work from menu FPS or resolution changes alone.

## Task 4: Optimize one measured bottleneck at a time

**Files:** Conditional on Task 3: `runtime/com.c`, `runtime/metal.m`, `runtime/perflog.c`, `tools/build_native.py` or translation tooling. Use the connected tests listed below for whichever path changes.

**Interfaces:** Preserve D3D/Metal resource ownership, ordering, shader semantics, physics timing and mod behavior.

- [ ] Select the largest avoidable cost in the HQ visuals 1080p race and state the expected mechanism and metric before editing. Do not preselect a renderer rewrite or general threading change.
- [ ] For CPU-bound frames, inspect repeated state work, data copies, allocation, dispatch and generated-code hotspots. Reassess the known D3DX `-O0` shard only if samples show it matters.
- [ ] For GPU-bound frames, inspect redundant passes, bandwidth, texture traffic and render-target transitions while preserving output.
- [ ] For readback-bound frames, retain the exposure algorithm and required pixel availability; reduce avoidable submission, copying and waiting without silently skipping or delaying its result.
- [ ] For compilation/streaming spikes, improve reuse and lifetime where measured. Preserve the existing shader deduplication and namespace fixes.
- [ ] Add a failing correctness regression for each nontrivial change, then implement it and run the relevant shader, GPU vertex cache, readback, query or widescreen tests.
- [ ] Repeat the same race segment three times before and after. Keep changes only when improvement exceeds run-to-run noise, frame-time tails do not regress, and output/behavior remains correct.
- [ ] Commit each verified optimization separately. Repeat until the agreed target is met or the next limiting cost is documented with measurements.
- [ ] Validate sustained 60 FPS in all three two-minute HQ visuals 1080p runs, with frame-time tails and visible smoothness reported. A menu result or short peak is insufficient; an average that conceals recurring long stalls does not establish smooth play. After this milestone, apply relevant improvements to Full HQ and measure its remaining costs separately.

**Deliverable:** Measured improvements attributable to code changes, with preserved visual and gameplay behavior. Reassess scope after the baseline rather than promising a speedup or completion date in advance.

## Task 5: Package, report and validate normal use

**Files:** `runtime/launcher.m`, `tools/package_app.py`, `README.md` and applicable launcher tests.

**Interfaces:** Existing launcher modes and resolution selection; existing single-entry app builder and safe installation flow.

- [ ] Label launcher resolution as render resolution and explain that its value controls output despite the legacy in-game label. Verify selected and actual drawable dimensions agree after startup and Video Options changes.
- [ ] Run `.venv/bin/python -m unittest discover -s tests` and the real Metal/UI tests required by the changed paths. Report skipped checks explicitly.
- [ ] Play through a menu-to-race transition, an intro/story video and in-engine cutscene; check music, engine audio, controls, pause, restart, return, save/reload and repeated graphics changes.
- [ ] Publish a local before/after table for all three modes using the controlled race. Document any unmet target and recommended settings without presenting reduced quality as an optimization result.
- [ ] Package and verify the signed ARM64 app, original local icon and all mode data. Replace the Applications copy only when it is not running, with rollback available.
- [ ] Verify visible fullscreen startup and gameplay from the exact installed build. Obtain user confirmation of normal fullscreen behavior before closing the intermittent bug.

**Deliverable:** A verified installed build and an honest performance report. Repository publication remains a separate authorized action.
