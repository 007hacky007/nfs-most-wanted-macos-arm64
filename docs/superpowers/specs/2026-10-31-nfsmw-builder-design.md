# NFSMW Builder - design

Date: 2026-10-31. Status: approved. The owner accepted the recommendations for D2, D3, D4, D6, D7 and D8 on 2026-10-31 and deferred the licence questions D1 and D5.

Reference: the NFSV Builder (NFSV repo, branch `nfsv-builder`): `docs/superpowers/specs/2026-10-30-nfsv-builder-design.md`, its plan, its mockups and its ledger. This document repeats what still applies so it can be read alone, and marks what is different for NFSMW.

## Why

Building NFSMW today means opening Terminal, installing the Xcode command line tools, installing Homebrew, running `brew install python cmake boost xz cabextract rust`, and running `./build.sh <source>`. The build then needs about 60 GB of free space, a 3.34 GB download and a long wait. That loses most regular players. The goal is a downloadable app that a non-technical Mac user can double-click, that tells them in plain words what is missing, fixes it with one button per item, and then builds their own `NFSMW.app` from their own game copy.

The translated game code is derived from each user's own `speed.exe`, and the produced app contains the user's own game files, so a prebuilt game can never be shipped. Every user's Mac must still compile it. The Builder makes the existing local build painless; it does not replace it.

## What gets built

1. **NFSMW Builder.app** - a small native Swift app with a pre-flight checklist and a build progress view. Code copied from the NFSV Builder and adapted.
2. **Bundled helper tools** - a prebuilt `innoextract` and RTPatch decoder, built by CI from the same pinned sources the CLI builds today, so regular users need no Homebrew (owner decision D2, recommended option C below).
3. **A GitHub Actions release pipeline** - on a version tag it tests, builds the helpers and the Builder, packs a DMG and publishes a GitHub Release.
4. **A DMG** with an illustrated background that teaches the Gatekeeper "Open Anyway" step, in the owner's latest picture style.
5. **README update** - the Builder becomes the primary way to build; `./build.sh` stays documented for power users and LLM agents.

## Goals

- A regular user never opens Terminal and never installs Homebrew.
- Every missing dependency is shown as a red/amber/green row with a button that resolves it.
- One build logic: the Builder drives the same Python pipeline as `./build.sh` (`tools/build_app.py` and friends). No second implementation of checksums, disc extraction, patching, translation, compiling or packaging. Helpers are built from the same pinned sources and source edits the CLI uses, and their outputs are checked against the same SHA-256 pins.
- A wrong game copy produces a message that names the required release in plain words, and a "Which copy works?" view with the accepted versions, file counts, total sizes and SHA-256 values.
- The 3.34 GB HQ download shows real progress, survives a dropped connection, and can be replaced by a file the user already has.
- Releases are fully automatic from a `v*` tag.
- The user understands, before launching, that macOS will block the unsigned app and exactly which buttons to press.

## Non-goals

- Apple notarization or Developer ID signing. Everything is ad-hoc signed (`codesign --sign -`).
- Removing the Xcode command line tools requirement. clang must run on the user's Mac; the Builder can only trigger Apple's installer.
- Installing the Builder. It runs straight from the mounted DMG.
- Intel Macs, other regions, the DVD edition, Most Wanted (2012), console releases, repacks, or any input the CLI does not already accept.
- Making the HQ package optional (see "HQ package" below; it is a build input for every mode).
- Removing or rewriting `build.sh` / the Python tools. The CLI keeps working with Homebrew.

## Anti-goals (failure even if it technically works)

- Any EA code, game asset, translated function, patched executable, patch archive or HQ file in the repo, CI artifacts, DMG or Builder bundle.
- Anything that makes the Builder look like piracy or sketchy software: dark "warez" styling, scary wording, unexplained password prompts.
- Modifying the user's game copy, any folder or file the user supplied (including a downloaded HQ zip they point at), their existing saves, any Python installation or any Homebrew installation they already have.
- Telemetry, analytics or any network traffic beyond the downloads described here.
- Personal data of the owner anywhere in the app, DMG, workflow or release (public repo `007hacky007/nfs-most-wanted-macos-arm64`, published under the `007hacky007` pseudonym).
- Em-dashes or en-dashes in any user-facing text or docs (hyphen-minus only).
- Leaving tens of gigabytes of hidden build files behind without telling the user.

## Licence questions (D1, D5)

Deferred by the owner on 2026-10-31. This design adds no release guard, no provenance list and no permission file, and it does not change `LICENSE`, `third_party/` or the DMG wording. The owner decides on licensing separately before the first published release.

## Constraints

- Apple Silicon only. **The Builder requires macOS 12 or newer** (the Swift toolchain's deployment floor, NFSV ruling 7). The produced `NFSMW.app` keeps `LSMinimumSystemVersion` 11.0 and `./build.sh` keeps working on 11.
- The pipeline needs **Python 3.12+** (`hashlib.file_digest`, `tarfile` `filter='data'`) with `capstone==5.0.9` and `pefile==2024.8.26` (`requirements.txt`). The private Python pinned in the NFSV Builder (python-build-standalone 3.12.16) qualifies.
- `build_app.py` checks for `clang`, `cmake`, `cabextract`, `rustc` and `codesign` on `PATH`. The Builder runs the pipeline with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, so the pipeline must learn to use the bundled helpers and the system `tar` instead (see Dependencies).
- Every Python tool resolves paths from `ROOT` and writes `.venv`, `gen/`, `out/` under it. Downloads are cached in `ROOT/out/downloads` today. The Builder needs the cache outside its versioned workspace, so a 3.34 GB download survives a Builder update: new `--cache-dir` flag and `NFSMW_CACHE_DIR` override, CLI default unchanged.
- Peak disk use is about 60 GB in the workspace (README figure; the builder measures it). The produced app is about 15 GB because it contains the user's verified game files and the Standard, HQ visual and Full HQ data trees.
- When launched from a DMG the Builder's own bundle is read-only and may be App-Translocated to a random path.
- Public GitHub repo under the `007hacky007` pseudonym. Commits use the `007hacky007` identity; no AI attribution in commits, release notes or docs.

## Dependencies (owner decision D2)

What each Homebrew package is for today:

| Package | Used by | Needed when | Replaceable by |
| --- | --- | --- | --- |
| `python` | everything | always | the Builder's private Python (as NFSV) |
| `cmake` | `tools/build_hq_extractor.py`, configures innoextract | every build (the extractor is rebuilt in a temporary stage each time) | not needed when innoextract comes prebuilt |
| `boost` | innoextract links Boost iostreams, filesystem, date_time, system and program_options | every build | static libraries inside a prebuilt innoextract. Headers only are **not** enough: iostreams, filesystem and program_options are compiled libraries |
| `xz` | innoextract's LZMA support (the macOS SDK ships `liblzma.tbd` but no `lzma.h`) | every build | static liblzma inside a prebuilt innoextract |
| `cabextract` | `game_sources._extract_discs` (always, for disc input: `DirectX/Jun2005_d3dx9_26_x86.cab` on Disc 1) and `install_game.supply_d3dx` (folder input without `d3dx9_26.dll`: the HQ zip's `Redist/dx/Jun2005_d3dx9_26_x86.cab`) | every disc build; some folder builds | **`/usr/bin/tar`** (bsdtar/libarchive, part of macOS). Verified here: `/usr/bin/tar -xOf` on the HQ zip's cabinet produced `d3dx9_26.dll` with exactly the pinned SHA-256 `8ea96fe0...c5bc78`. The Disc 1 cabinet (a different 1,065,813-byte file) still has to be checked the same way; the output hash is verified either way |
| `rust` | `tools/official_patch.py` compiles `tools/rtpatch_decode.rs` plus `third_party/rtpatch/codec.rs` (523 lines, MIT) on every build to decode the seven official 1.3 replacement records | every build | a prebuilt decoder, a C port compiled with the user's clang, or a Python port. Every decoded record is SHA-256 pinned, so any implementation is self-checking |

Python packages do not help much: there is no maintained pure-Python reader for Inno Setup 6.6 installers (even innoextract needs an unmerged fork plus local patches for 6.5+ slices), and Python's `lzma` module does not help a C++ tool. A Python RTPatch port is possible but slow and new code.

Options:

- **A. The Builder installs Homebrew packages.** If Homebrew exists: `brew install cmake boost xz cabextract rust`, roughly 1 GB of downloads and several minutes, unpinned versions (a future CMake or Boost can break the innoextract build), and it changes the user's own Homebrew (it can upgrade packages they already rely on, which is an anti-goal). If Homebrew is missing: Homebrew's own `.pkg` installer or its Terminal script, both needing an admin password; standard (non-admin) accounts cannot do it at all. Least new code, worst user experience.
- **B. Pinned upstream downloads built on the user's Mac.** Kitware's macOS CMake tarball (about 55 MB), Boost source (about 130 MB, then a b2 build of five libraries), xz source for headers, cabextract source (configure and make), and the standalone Rust components (about 100 MB compressed, about 400 MB unpacked), all into the Builder's private folder with pinned SHA-256s. About 300 MB extra download, about 10 extra minutes, and a lot of fragile per-Mac build logic. Not recommended.
- **C. Prebuilt helpers in the Builder plus the system `tar` (recommended).** The release workflow builds `innoextract` from the same pinned source (`psi29a/innoextract` at `8f317ad`, SHA-256 `b9d6fadd...`) with the same `patch_source()` edits, linked against Boost and liblzma that CI builds from pinned sources for macOS 12, and builds the RTPatch decoder from `tools/rtpatch_decode.rs` with CI's `rustc`. Both are ad-hoc signed, recorded with their SHA-256 in `helpers.json`, and bundled in the Builder's build sources. cabextract is replaced by `/usr/bin/tar` for everyone, CLI included. The pipeline gains `--helpers DIR`; without it the CLI behaves as today. Cost: a few MB more in the DMG, one CI job that builds Boost (cached between runs), new licence notices (innoextract zlib, Boost BSL-1.0, xz 0BSD, rtptool MIT). Users install nothing but Apple's command line tools.
- **D. Ports instead of binaries.** Port the RTPatch codec to C (compiled by the user's clang) or Python, which would also drop Rust from the CLI. innoextract still needs option C or A. A possible follow-up, not needed for the Builder.

Recommendation: **C**, and also switch the CLI's CAB step to `/usr/bin/tar` so `cabextract` leaves the README (owner decision D7).

## The Builder app

### Window (layout A, single window)

Same layout as the approved NFSV mockup option A: one window, one checklist. Each row has a status light, a title, one line of plain explanation, and when the row is not green, a button that fixes it. Below the list, a large **Build NFSMW.app** button that is enabled only when no row is red. A new NFSMW window mockup is made from the NFSV one before implementation (plan Task 0).

Lights: **green** ready, **amber** will be handled automatically during the build (not blocking), **red** blocking, **grey** checking.

Rows, in order:

| Row | Green when | Not green | Button |
| --- | --- | --- | --- |
| Mac | Apple Silicon and macOS 12+ | Red, with the reason. Cannot be fixed. | none |
| Xcode command line tools | `xcode-select -p` points at a folder with clang, and `/usr/bin/codesign` exists (never probe through `xcrun` or `/usr/bin/clang`: those shims pop Apple's installer) | Red, "needed to compile the game on your Mac, about 2 GB from Apple" | **Install...** runs `xcode-select --install`; the row re-checks every 3 s until green. |
| Build tools | the private Python is installed with the pinned marker, the workspace venv matches `requirements.txt`, and the bundled helpers verify against `helpers.json` | Red, "about 90 MB download" (builder to re-measure) | **Install** downloads Python and sets up packages, with inline progress. |
| Downloads | all four pinned downloads are in the Builder's cache and verify (official 1.3 patch 12.8 MB, WidescreenFix 8.9 MB, Most Wanted HQ 1.20.9 3.34 GB, plus the innoextract source only when helpers are absent) | Amber, "3.36 GB, downloaded during the build" | **Download now** (optional, with byte progress) and **Use a file I already have...** for `MW_HQ_1.20.9.zip`. |
| Game copy | the chosen copy passed the full check | Red until chosen; red with the plain-language reason when rejected | **Choose...** plus **Which copy works?**. Drag and drop works too. |
| Destination | the target folder is writable, and any existing `NFSMW.app` there is ours (`CFBundleIdentifier` `local.nfsmw.native`) | Red if not writable, or "There is a different NFSMW.app in this folder. Choose another folder." | **Change...** picker. Default `/Applications`. |
| Free disk space | enough free space on the workspace volume, plus about 15 GB on the destination volume when it is a different volume | Red with how much is needed and where | none |

The game-copy check runs once build tools are installed (grey "checked once build tools are installed" before that) and again whenever the choice changes. It reads about 2.2 GB (disc archives) or 3 GB (folder), so it shows grey "Checking your game copy..." for a few seconds to a minute.

### Game copy row

Inputs the CLI accepts today, and how the row takes them:

- **A folder** with the installed game (`speed.exe`, `CARS`, `GLOBAL`, `MOVIES`, `SOUND`, `TRACKS`), or a folder holding the four ISO images or the BIN/CUE set. `stage_game` already decides which by looking for `speed.exe` and image files.
- **Several files**: the four `.iso` files, or the `.cue` (or `.bin`) files of the set. The open panel allows multiple selection and both files and folders. Dropping several files at once works the same way. Order and file names do not matter (disc roles come from contents).
- The row title shows what was chosen: the folder name, or "4 disc images" with the names in a tooltip.
- Picking one image only is accepted as a choice and then rejected by the check with "Found 1 of the 4 discs. Choose all four disc images together, or a folder that contains them."

The Builder passes the chosen paths as separate argv entries to the pipeline. It never writes into the chosen folder or next to the chosen files.

### Wrong game copy: what the user sees

New owner requirement for all builders. The red row message names the required release in plain words, then the first problems:

- Wrong or modified folder: "This is not the supported game copy. NFSMW Builder needs Need for Speed Most Wanted (2005) for PC, USA English Black Edition (4 CDs), original or updated to v1.3. 37 of 1,407 files are missing or different, for example speed.exe, GLOBAL/GlobalB.lzc and TRACKS/L2RA.BUN."
- Incomplete disc set: "Found 3 of the 4 discs. Disc 4 (the image that contains 3compressed.zip) is missing."
- Wrong disc: "disc 2.iso is not one of the four supported discs: its 1compressed.zip has a different size or checksum."
- Nothing usable: "This folder has no speed.exe and no disc images."

**Which copy works?** opens a sheet with:

- The required release in one sentence, and what does not work (other regions, the DVD edition, Most Wanted (2012), console versions, repacks, modified copies).
- "The 4 original CDs (ISO or BIN/CUE)": a table of the four archives inside the discs, with exact sizes and SHA-256 values (Disc 1 `0compressed.zip` 612,595,273 bytes `d3a3179f...`, Disc 2 `1compressed.zip` 731,641,113 bytes, Disc 3 `2compressed.zip` 731,635,509 bytes, Disc 4 `3compressed.zip` 169,410,767 bytes; 2,245,282,662 bytes together). A line explains that whole-ISO checksums are not used.
- "An installed game folder": 1,407 required files, 3,028,017,159 bytes as installed from the discs, or 3,028,022,871 bytes with the official 1.3 files; and the two accepted `speed.exe` files (original 7,250,800 bytes `2cf8bdbf...`, official 1.3 7,254,894 bytes `e8019e0d...`).
- "Your copy": the check's result, with the first 20 failing files, each with what was found (missing, or size and SHA-256) and what is accepted.
- **Copy details** (to the clipboard, for a bug report) and a link to `tools/game_checksums.json` at the Builder's tag on GitHub for the full list.

All of these values come from `tools/game_checksums.json` through a new `builder_cli.py accepted-copies` command. Nothing is typed into Swift. The README "Checksums and byte sizes" section gains the file count and total sizes, and a test asserts that the README numbers equal those computed from `game_checksums.json`, so the three places cannot drift.

How it works underneath: today `stage_game` raises at the first problem ("unsupported size or checksum: <path>", "missing required game file: <path>", "missing disc roles; supply all four game images"). A new `check_sources(sources)` in `tools/game_sources.py` reuses the same profile, folder walk, CUE parser, disc inventory and digest helpers, never writes anywhere, and collects every problem instead of stopping (with the first 20 kept in detail and the rest counted). `stage_game` stays the authority during the build; a test asserts both agree on accept or reject for every existing fixture.

### Downloads and the HQ package

- The HQ package is **required for every mode**, not only HQ. The supported canonical runtime (`80774c2e...`) is reconstructed from the HQ package's game image (`8393f348...`) plus the official 1.3 resources (`runtime_image.build_standard_runtime`), and `hq_variants` / `prepare_public_hq` need the HQ tree. Making HQ optional would mean a different translation input, which is a pipeline project, not a Builder one. The launcher's Standard / HQ visuals / Full HQ choice stays at play time.
- Time: 3.34 GB is about 9 minutes at 50 Mbit/s and about 45 minutes at 10 Mbit/s. The Downloads row and the build view show received and total bytes, speed and an estimate.
- Today `patch_sources._download` gives up after `min(7200, max(300, size / 256 KiB))` seconds, which is 2 hours for the HQ zip: anything below about 3.7 Mbit/s fails every time, and a failure throws the partial file away. The plan changes this in the pipeline (shared with the CLI):
  - A stall timeout (no bytes for 120 s) instead of a total budget for large files.
  - Resume: the partial file is kept under a fixed name in the cache, and the next attempt asks for the rest with an HTTP `Range` request. A `206` with a matching `Content-Range` continues; anything else starts over. The final size and SHA-256 pin is unchanged, so resume can never produce a wrong file.
  - Byte progress through a callback, which `--progress` mode prints as events.
- ModDB is reached by reading its mirror page. If that ever stops working, the row says so and offers **Use a file I already have...** plus a button that opens the ModDB page in the browser. A chosen file is verified (size and SHA-256, existing `verify_patch`), then copied into the cache (an APFS clone when on the same volume). The user's file is never moved, renamed or written next to.
- The download cache lives at `~/Library/Caches/NFSMW/downloads` (outside the versioned workspace, excluded from Time Machine by macOS). The CLI keeps `out/downloads` unless `NFSMW_CACHE_DIR` or `--cache-dir` is given (sharing the cache with the CLI by default is owner decision D8).

### Building

Pressing **Build NFSMW.app** swaps the checklist for a progress view in the same window: the steps below with the current one highlighted, an overall progress bar, the download byte counter while downloading, an elapsed time, and a collapsed **Show details** log. A note says "This takes about N minutes. You can keep using your Mac." (N measured during implementation; about 18 minutes on the owner's Mac with downloads cached, longer on a first build.) The Builder keeps the Mac from idle-sleeping while a build or download runs (`ProcessInfo.beginActivity`), and releases it when done.

Pipeline steps (`--progress` step ids, in order; weights are first guesses for the progress bar and are re-measured):

| id | What the user reads | Weight |
| --- | --- | ---: |
| `check` | Checking your game copy | 2 |
| `downloads` | Downloading patches and Most Wanted HQ (3.36 GB) - byte progress inside | 8 |
| `tools` | Preparing the extraction tools (verifies helpers, or builds innoextract on the CLI) | 1 |
| `game` | Copying and checking all game files | 6 |
| `patches` | Applying the official 1.3 patch, D3DX and WidescreenFix | 2 |
| `hq` | Unpacking Most Wanted HQ | 8 |
| `variants` | Preparing Standard, HQ visual and Full HQ data | 6 |
| `translate` | Translating the game to C (`gen.sh`) | 12 |
| `audio` | Preparing native audio callbacks | 2 |
| `modules` | Generating the six original runtime modules | 8 |
| `bootstrap` | First native build and module start-up | 10 |
| `runtime` | Finding the remaining code states (repeats, "round 2 of at most 12") | 20 |
| `final` | Final native build and verification run | 10 |
| `package` | Packaging and signing NFSMW.app with your game files | 5 |

`check` is new: the pipeline verifies the game copy before it starts the 3.34 GB download (today the downloads come first). Several steps write their detailed output to log files (`run()` in `prepare_public_hq.py`); a failure event carries that log path, and **Copy log** includes its last 200 lines.

A **Cancel** button stops the whole process group (python, gen.sh, clang workers, innoextract, the headless engine runs used for preparation).

### When it finishes

- **Success:** `NFSMW.app` (about 15 GB) is put in the destination. On the same volume this is a move of the workspace copy (instant); on another volume a copy with a progress line. If an older `NFSMW.app` with our bundle id is there it is replaced only after the new one is fully in place; if that game is running, ask the user to quit it first. Quarantine is removed from the result. The window shows a green "Ready" state with **Play** and **Show in Finder**. The intermediate build files (tens of GB) are removed automatically after a successful install, keeping the download cache and the private Python, and the result screen says how much space was freed (owner decision D3; alternative: a "Remove build files" button as in NFSV). A small **Remove downloads (3.4 GB)** button frees the cache.
- **Failure:** the failing step in plain words (for example the wrong-copy message above, or "The Most Wanted HQ download did not finish. Click Try again to continue where it stopped."), the log expanded, **Copy log**, **Try again** (back to the checklist) and **Remove build files** with the size shown.

### Where it works

- Workspace: `~/Library/Application Support/NFSMW Builder/<builder version>/`, copied from the bundled build sources, quarantine removed, excluded from Time Machine (`isExcludedFromBackup`). Workspaces of other Builder versions are removed on launch (they are the Builder's own files; skipped while another Builder holds their build lock).
- Private Python: `~/Library/Application Support/NFSMW Builder/python/`, the same pinned python-build-standalone 3.12.16 build as NFSV, verified before extraction, quarantine removed. Packages are installed by the existing `environment()` logic into the workspace `.venv` from PyPI.
- Helpers: inside the bundled sources (`helpers/innoextract`, `helpers/rtpatch-decode`, `helpers/helpers.json`), so they are copied into the workspace and lose any quarantine before they run.
- Downloads: `~/Library/Caches/NFSMW/downloads`.
- The Builder never touches `/usr/bin/python3`, Homebrew or anything on the user's `PATH`.

### Bundled sources

At release time the Builder bundle gets the tracked files the pipeline needs from the tagged commit: `build.sh`, `gen.sh`, `requirements.txt`, `LICENSE` (`package_app.py` copies it into the game), `tools/`, `runtime/`, `third_party/`, plus the CI-built `helpers/`. Not `tests/`, `docs/`, `vendor/`, `gen/`, `out/`, `work/`, `game*/`, `pack.sh`. That is 182 tracked files today, the largest `tools/game_checksums.json` at 0.5 MB. `make_builder.py` refuses to bundle any file with a game or archive suffix (`.exe`, `.dll`, `.asi`, `.bun`, `.lzc`, `.big`, `.zip`, `.iso`, `.bin`, `.cue`, `.cab`) or any tracked file over 2 MB; the two helper binaries are added separately and checked against `helpers.json`. The Builder's version is the tag, and the build it produces matches the code at that tag.

### Look

- Native macOS look (system fonts, standard controls, light and dark mode).
- App icon: friendly bright gradient rounded square with a white generic car and speed lines, a different colour from NFSV's blue so the two are not confused (for example orange to amber). No dark tile, no real car model or brand. Shown in the Task 0 mockup for approval.
- The `NFSMW.app` it produces keeps its current icon, extracted from the user's own `speed.exe`.

### Names

- Builder: **NFSMW Builder.app**, executable `NFSMWBuilder`, bundle id `local.nfsmw.builder` (matches the existing `local.nfsmw.*` namespace; NFSV used `org.nfsv.builder`, owner decision D6).
- Produced game: `NFSMW.app`, bundle id `local.nfsmw.native` (from `tools/package_app.py`). Running check and replace check use that id.
- DMG asset: `NFSMW-Builder.dmg` (unversioned), volume name `NFSMW Builder <version>`.
- Event prefix: `NFSMW-EVENT ` followed by one JSON object.

### Builder's choices

Exact disk-space and download numbers (measured), error wording beyond the examples, weights of the progress steps, the helpers' build flags.

## Distribution

### DMG

Same layout as NFSV's final version, with the owner's latest picture style:

- One window containing only **NFSMW Builder.app** over an illustrated background. **No Applications shortcut**; the Builder runs from the DMG. Background 760 x 600 points with the bottom 60 px left blank (Finder's path and status bars can cover them); window 760 x 628.
- The illustrations must read as pictures, not real windows: the Gatekeeper alert and the Privacy & Security drawings are **greyscale** (contrast about .85), with **no traffic lights**, drawn as slightly tilted photo cards with a white border (alert about +2 degrees, Settings about -1.5 degrees), each with a small **"EXAMPLE - WHAT YOU WILL SEE"** label above it. The red pencil marks stay in colour. Labels sit clear of the outlines, the cards clear of the bottom text, and the circles still sit on Done, Open Anyway and the sidebar row.
- Content: the Builder icon circled with "1. Run me" (the real icon placed by Finder in the drawn circle); the "\"NFSMW Builder\" Not Opened" alert with Apple's wording and **Done** circled, "2. Click Done"; System Settings > Privacy & Security with the real hand icon, the sidebar row circled, "\"NFSMW Builder\" was blocked to protect your Mac." with **Open Anyway** circled, "3. Open System Settings" / "Privacy & Security, scroll down" and "4. Open Anyway".
- Three bottom lines, verbatim:
  - "Why? NFSMW Builder is free and open source, but it is not signed by Apple, so macOS asks you to confirm it once."
  - "On macOS 14 or older: right-click NFSMW Builder and choose Open."
  - "Comfortable with Terminal? Eject, run `xattr -d com.apple.quarantine ~/Downloads/NFSMW-Builder.dmg`, open again."
- Do not add back: an Applications shortcut, "no need to install it", "then your password", a dark icon.
- The background is an HTML source rendered to 1x and 2x PNGs with headless Chrome; the PNGs are committed so CI needs no fonts.

### Release pipeline

`.github/workflows/release.yml`, on tags `v*`, runner `macos-15` (arm64), `permissions: contents: write`:

1. Check out the tag; Python 3.12; `pip install -r requirements.txt dmgbuild==1.6.7`.
2. Tests that need no game copy: the Python `unittest` suite with a CI-safe subset (tests needing `gen/`, `out/`, a Metal device, a window server or game files are skipped, not refactored), and `swift test --package-path builder`.
3. Build the helpers (`python tools/build_helpers.py --output helpers`): pinned Boost and xz sources built statically for macOS 12 (cached with `actions/cache` keyed on their SHA-256s), innoextract from the pinned source with `patch_source()`, the RTPatch decoder with `rustc`. Checks: `LC_BUILD_VERSION` minos 12.0, `otool -L` lists only `/usr/lib` and `/System` libraries, `innoextract --version` names Inno Setup 6.6.1, the decoder decodes a synthetic test record.
4. Build NFSMW Builder.app (arm64, macOS 12), stamp the version from the tag, bundle the sources and helpers, ad-hoc sign.
5. Build the DMG with `dmgbuild` and its SHA-256.
6. `gh release create` with auto-generated notes and the DMG plus its `.sha256`.

No secrets beyond the default `GITHUB_TOKEN`. No game files are ever available to CI, so CI cannot run an end-to-end game build. Release notes, workflow and commits contain no AI attribution and no personal data.

## Open risks for the builder to verify early

- **Disc 1 cabinet through `/usr/bin/tar`.** Verified for the HQ zip's cabinet only. Check the disc's `DirectX/Jun2005_d3dx9_26_x86.cab` the same way (output must hash to `8ea96fe0...`), and check `/usr/bin/tar` on macOS 12 (older libarchive). Fallback: bundle a CI-built cabextract (GPL-3, with its source offer) as a third helper.
- **Static innoextract for macOS 12.** Homebrew bottles on the runner target macOS 15, so linking them would put macOS 15 objects into a binary that claims 12 (the NFSV minos lesson). Build Boost and xz from pinned sources with `-mmacosx-version-min=12.0` instead, and check every object.
- **Headless preparation runs.** The pipeline runs the freshly built engine up to about 14 times (`--prepare-hq-modules`, `--prepare-hq-runtime`, 250 s timeout each). Confirm they show no windows or Dock icons when started from the Builder, work while the screen is locked, and are stopped by Cancel.
- **Peak disk and RAM.** Measure the real peak in the workspace (README says 60 GB) and the memory high-water mark (genall with 128 shards, 8 clang workers); decide whether 8 GB Macs need a warning row.
- **ModDB.** Mirror scraping can break at any time; the "Use a file I already have" path must work without network.
- **Open Anyway from a mounted DMG**, **quarantine propagation** (private Python, workspace, helpers and especially the 15 GB `NFSMW.app` must open without a Gatekeeper prompt), **App Translocation** and **writing to `/Applications`** as in NFSV.
- **E2E tests must never touch the owner's folders.** In the NFSV e2e test, pointing a cache variable at a game folder let the pipeline replace a file there. NFSMW's `_download` also replaces an unverified cached file with `os.replace`. E2E tests clone the game source and any cache into a temporary folder first (`cp -c`, instant on APFS) and never pass an owner folder as cache or output.

## README

Add a top-level "Easiest way" section: download `NFSMW-Builder.dmg` from Releases, open it, follow the pictures, fix any red rows, click Build, then Play. Say that it needs about 60 GB free during the build and downloads 3.36 GB. Keep the Terminal instructions under "Build from Terminal". In "What you need", say the Builder installs its own Python and tools and only the command line tools come from Apple, and that the Builder needs macOS 12 or newer. Add the file count and total sizes to "Checksums and byte sizes". Drop `cabextract` from the brew line if D7 is accepted.

## Differences from the NFSV Builder (summary)

| Topic | NFSV | NFSMW |
| --- | --- | --- |
| Extra build tools | none | innoextract (cmake, Boost, xz), cabextract, Rust: replaced by bundled helpers and `/usr/bin/tar` |
| Game input | one folder or one image | folder, image folder, or 4 images / BIN-CUE set picked or dropped together |
| Verification | about 30 files, first error | 1,407 files or 4 disc archives, collect all problems, "Which copy works?" |
| Downloads | 15 MB | 3.36 GB, resumable, byte progress, "use a file I already have" |
| Disk | 3 GB | about 60 GB workspace, 15 GB app, automatic cleanup |
| Steps | 7 | 14, with a repeating `runtime` step |
| Cache | `~/Library/Caches/NFSV` shared with CLI | CLI in `out/downloads`, Builder in `~/Library/Caches/NFSMW/downloads` |
| Install | copy | move on the same volume, refuse an unrelated `NFSMW.app` |
| DMG art | coloured window drawings | greyscale tilted photo cards with "EXAMPLE" labels |

## Owner decisions

- **D1 Licence.** Deferred by the owner.
- **D2 Dependencies.** Option C (bundled CI-built innoextract and RTPatch decoder, system `tar` for CAB). Affects plan Tasks 3, 5, 6, 14 and 16.
- **D3 Cleanup.** Remove the tens of GB of build files automatically after a successful install. Recommended: yes.
- **D4 HQ download.** Resume plus stall timeout in the shared pipeline, and a "Use a file I already have" fallback. Recommended: yes. HQ stays mandatory for all modes.
- **D5 Release wording.** Deferred by the owner; the DMG keeps the wording above.
- **D6 Bundle id.** `local.nfsmw.builder`. Recommended, unless the owner wants `org.*` like NFSV.
- **D7 CLI cleanup.** Use `/usr/bin/tar` in the CLI too and drop `cabextract` from the README. Recommended: yes.
- **D8 Shared cache.** Keep the CLI cache in `out/downloads` (unchanged) and give the Builder its own cache. Recommended: keep separate; `NFSMW_CACHE_DIR` lets power users share.
