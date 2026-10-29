# Most Wanted for Apple Silicon

Build a local macOS version of Need for Speed Most Wanted (2005) from your own
Windows game copy. **This repository contains no EA game code or game assets.**
You must supply the game. Extracted files, downloaded patches and locally
generated game code remain in ignored build directories.

The port compiles the game into ARM64 and renders through Metal. Its macOS
launcher offers resolution and three game modes: Standard, HQ visuals only,
and Full HQ. The build targets **Most Wanted (2005) PC v1.3, USA English
Black Edition**. Use the verified original four-CD data described below; the
builder installs the official 1.3 update automatically.

## Build your app

You need an Apple Silicon Mac, internet access and about 60 GB of free space
for the build. Install the Xcode command-line tools and build dependencies
once. The second command uses Homebrew and supplies Python 3.12 or later:

```sh
xcode-select --install
brew install python cmake boost xz cabextract rust
```

Open Terminal in this repository and run one command:

```sh
./build.sh "./my-game-copy"
```

The source can be:

- A folder containing extracted game files, including `speed.exe`, `CARS`,
  `GLOBAL`, `MOVIES`, `SOUND` and `TRACKS`.
- A folder containing all four supported ISO disc images.
- A folder containing the supported BIN/CUE disc set.
- All four images supplied as separate arguments, for example
  `./build.sh "./disc 1.iso" "./disc 2.iso" "./disc 3.iso" "./disc 4.iso"`.

Image filenames and argument order do not matter. BIN/CUE support covers
single-track MODE1/2048 and MODE1/2352 data discs. Keep each CUE beside its BIN.
Audio tracks, multiple tracks and nonzero track offsets are not supported.

The script creates its Python environment, extracts and checks your game files,
downloads and verifies the patches, builds native extraction tools, generates
the game and mod code locally, and signs the app for local use. Windows
installers are read as data and are never executed. The initial download
includes the 3.34 GB HQ package; the launcher lets you choose whether to use
its visual assets or full mod behavior. Verified downloads are cached.

When the build finishes, open **`out/Most Wanted.app`**. Your verified game copy
is bundled inside the app, so you can move it to Applications. Choose a
resolution and game mode, then click Play. Your source copy is preserved.
A failed build preserves the previous app; diagnostic logs remain under `out/`.

## Supported game copy

**Expected data edition:** the USA English Black Edition four-CD PC release
of Need for Speed Most Wanted (2005). **Prepared and tested game version:**
**v1.3**. This does not refer to Most Wanted (2012), a console release or an
arbitrary executable labeled 1.3.

An extracted copy can contain the verified original disc files or their
official 1.3 replacements. The builder always applies the pinned official
1.3 patch and prepares the supported runtime itself. You do not need to
install patches or find a replacement executable manually. Other regions,
DVD editions, repacks, incomplete copies and unknown modified files are not
accepted by the current checksum profile.

Compatibility is determined by the **extracted files and executable bytes**,
not filenames, version strings or a whole-ISO/BIN checksum. Every required
file is checked by size and SHA-256. The profile describes 1,406 required game
asset files plus `speed.exe`, with additional checks for recognized optional
files such as the supplied D3DX DLL. All accepted per-file alternatives are
recorded in `tools/game_checksums.json`. The Checksums and byte sizes section
below explains which files each checksum describes.

### What has been tested

| Input or runtime | Verification performed |
| --- | --- |
| USA English Black Edition, four ISO discs | Complete fresh extraction, per-file checks, official 1.3 patching, HQ preparation, native translation and signed app build |
| Same four-disc payload in BIN/CUE | Actual disc extraction and extracted-file checks passed; uses the same remaining build pipeline, without a separate complete BIN-to-app build |
| Extracted, officially patched 1.3 installation | Actual file staging and checksum checks passed; a separate complete folder-to-app build has not been run |
| Original disc executable and assets | Verified from the four-disc source and upgraded to 1.3 during the complete ISO build; the unpatched executable is not the runtime target |
| Prepared v1.3 Standard and HQ visuals | Menus, driving, pause/restart, sound/music, opening videos and following in-engine cutscene exercised in native runs |
| Prepared v1.3 Full HQ, HQ package 1.20.9 | Added-car driving, original module initialization, videos/cutscene and race controls exercised; final signed app with bundled files also drove and steered an automatic IS300 at 1280x720 |

These checks cover the identified edition and files. They do not establish
support for another release just because it reports the same version number.

Extra saves or configuration files in a supplied installation are not imported.
The builder copies only recognized game files. A damaged or incompatible
required file stops the build instead of producing a partially patched app.

## Patches

Patch payloads are downloaded during your build and are not included in this
repository. Exact URLs, sizes and SHA-256 pins are recorded in
`tools/patch_sources.py`.

| Patch | Version and source | Use |
| --- | --- | --- |
| Official update | 1.3, [EA original](https://largedownloads.ea.com/pub/patches/nfsmwpatch1.3.exe), with the checksum-matching [NFSPlanet mirror](https://dl1.nfsplanet.com/nfsmw/patches/nfsmwpatch1.3.exe) as fallback | All modes |
| WidescreenFix | [ThirteenAG's release](https://github.com/ThirteenAG/WidescreenFixesPack/releases/tag/nfsmw), pinned asset 558912001 | Native resolution, aspect, HUD and movie handling |
| Most Wanted HQ | 1.20.9, [author's ModDB download](https://www.moddb.com/downloads/start/233611) | Optional visual assets or full mod mode |

Full HQ selects English, modern shaders, Xbox 360 lighting, standard difficulty
and the original playlist with HQ audio. Movies and in-engine cinematics stay
enabled. It includes native integrations for X360Stuff 4.1, XboxRainDroplets,
Unlimiter 3.3.0.1338, ExtraOptions 10.0.1.1337, XenonEffects, MWFixes,
FEShadows 2.1, HDContentSupport 2.0, HDReflections 2.0, HUDAdapter,
MotionBlurController 1.0.0.100, SpeedReflect 1.2, TexWizard and ZPatchMW.
Visuals-only mode keeps standard gameplay, car list, shaders, audio and videos
while applying HQ world and existing-car visual files.

The build also obtains pinned native innoextract source from its upstream fork.
The required Microsoft D3DX9_26 DLL comes from the verified disc or the HQ
package's Microsoft redistributable. These inputs remain local to the build.

## Checksums and byte sizes

All sizes below are exact decimal byte counts. **None is a checksum or size
of a complete ISO, BIN or CUE file.** Different image containers can hold the
same accepted payload. Folder inputs do not need the disc ZIP files: their
extracted contents are checked directly.

### The executable you supply

You supply **one game copy**, with **one `speed.exe`**. Its normal source is
either the original Disc 1 or an installation updated with EA's official 1.3
patch. These are the two ordinary input versions in the table below. The
builder verifies your copy and prepares the same v1.3 native target from either
one. When building from disc images, it finds the original executable on Disc 1
automatically.

| Your copy | What the builder does |
| --- | --- |
| Original, unpatched USA English Black Edition discs or extracted files | Verifies the original executable and data, then applies official 1.3 |
| The same game data with the official 1.3 patch already installed | Verifies the patched files and prepares the supported runtime |

The following hashes identify the two ordinary source executables:

| Accepted source `speed.exe` | Exact size (bytes) | SHA-256 of the executable file |
| --- | ---: | --- |
| Original USA English Black Edition disc executable (unpatched) | 7250800 | `2cf8bdbf8095fa9e10ea552695404ae9c95b5b0367a7c830520c65a57896220a` |
| Official USA 1.3 replacement | 7254894 | `e8019e0d7b706beba5ec648a50108a9a13346695eba9ebe58b6d796260d3c4eb` |

To check an extracted executable manually on macOS:

```sh
shasum -a 256 "./my-game-copy/speed.exe"
stat -f '%z' "./my-game-copy/speed.exe"
```

### Files stored inside each original disc

**`0compressed.zip` is a file in the root directory of Disc 1.** It is part
of the original Windows installer and contains compressed game files. Your
ISO or BIN image contains this ZIP file as an ordinary file in its disc
filesystem. The ZIP is not a compressed ISO or BIN image.

To identify it, open or mount Disc 1 and look at its top-level files in Finder.
The tested image has the volume label `NFSMW_DISC1` and a file named
`0compressed.zip`. Discs 2, 3 and 4 similarly contain `1compressed.zip`,
`2compressed.zip` and `3compressed.zip` at their top level. The original
numbering starts at zero, although the physical discs are numbered 1 through 4.

**Give the builder all four disc images, or a folder containing them.** The
builder opens the images, finds these files, verifies their checksums and
extracts their game files automatically. You do not need to open or extract
the ZIPs yourself. For an already extracted game folder, these ZIPs are not
needed; the builder checks the individual game files instead.

Each checksum below covers only the named ZIP file **inside** its disc. The
volume labels are identifiers observed on the tested discs; the actual
compatibility check uses the archive filenames, sizes and contents. After
extraction, the builder also checks every required game file separately.

| Original disc | Tested ISO volume label | File at the disc's top level | Exact size of that file (bytes) | SHA-256 of that file |
| --- | --- | --- | ---: | --- |
| Disc 1 | `NFSMW_DISC1` | `0compressed.zip` | 612595273 | `d3a3179f4b794bab7cf633b1313b597d40934bb17a83d3e02b91af368624ee99` |
| Disc 2 | `NFSMW_DISC2` | `1compressed.zip` | 731641113 | `1ae6c9410f726afeec9a27fb8e9abd5864f53849eb65c2187f6747893ac7dd97` |
| Disc 3 | `NFSMW_DISC3` | `2compressed.zip` | 731635509 | `3fb6436c719cb01ec7002df41413dd163f57afff80f9cfb8f7e2c1c31f4c616c` |
| Disc 4 | `NFSMW_DISC4` | `3compressed.zip` | 169410767 | `b77b352d5cfa5ceae2b103d7989ed2ac7a86c58f430a3335687fb82b8723ee7a` |

### Downloaded patches

These pins cover the complete downloaded files, before extraction or decoding.
The official download is an EXE container; the other two downloads are ZIPs.

| Downloaded file | Exact size (bytes) | SHA-256 of the downloaded file |
| --- | ---: | --- |
| `nfsmwpatch1.3.exe` | 12777356 | `4c858e9b63ae2f856af7f1c090d5ce3d8c75246e9c0f7018ff57efb87addd0ef` |
| `NFSMostWanted.WidescreenFix.zip` | 8911715 | `7be912197ac19134d5a64dfe61225e4ef85d612c4f64b96045727c3bf6735df4` |
| `MW_HQ_1.20.9.zip` | 3337473092 | `1ff919737829ca46179c90740d32f6fed6797ad6b88a8daeaa6ecf255d184963` |

### Internal files the builder produces

The **6,029,312-byte runtime** is an intermediate file produced by this
project. It is the file used to translate the game into ARM64, with the
original v1.3 resources restored. It represents the prepared v1.3 code image,
rather than another retail release. You do not need to obtain or select this
file. The input checker also recognizes its exact bytes when reusing an older
locally prepared game folder.

Full HQ has a separate game/resource image supplied by the automatically
downloaded HQ package. It provides the selected HQ resources. These internal
files are created in the private build copy; your original copy is unchanged.
All three launcher modes use the supported v1.3 native game code.

| Internal build file | Purpose | Exact size (bytes) | SHA-256 of the file |
| --- | --- | ---: | --- |
| `.nfsmw/runtime.exe` | Canonical v1.3 input for ARM64 translation | 6029312 | `80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c` |
| `.nfsmw/full/speed.exe` | HQ 1.20.9 game/resource image | 5992448 | `8393f3487e3e024d6c2196d8adcd3f5b1b38077a893d9161a6f9ac61d587fa19` |

## Playing

- Original menus, profile creation and reload, Quick Race, and the opening
  Career sequence have been exercised.
- Driving, steering, pause, restart and return to the menu work in native runs.
- Music, engine and menu audio, attract video, opening story video and the
  following in-engine cutscene have been verified.
- The launcher provides 4:3, 16:9, 16:10 and other supported resolutions.
- Keyboard and game-controller input use native macOS interfaces.

Click the title screen to continue. Use arrows and Enter in menus, arrows to
drive, and Esc to pause. The window close button and Cmd-Q request a normal
game shutdown.

Saves live under `~/Library/Application Support/NFSMW/Saves`. HQ visuals and
Full HQ use separate `HQVisuals` and `HQFull` save folders. The latest app log
is `~/Library/Logs/NFSMW/last-run.log`.

This remains an experimental port. A complete Career playthrough, every car
and track, and every controller have not been tested. Full HQ is demanding;
the opening cutscene and driven races in development tests ran at roughly
18-31 FPS at 1920x1080. Network play is disabled.
The shader-ID collision responsible for black water has a tested Metal fix;
a clear view of the repaired water surface in a live race is still unverified.

The donor project's personal-use terms are preserved in `LICENSE`.
Additional notices are in the `third_party` directory. The app you build
contains your game files and locally generated game code.

## How native is it?

The build translates supported x86 game and D3DX instructions into C, then
Apple Clang compiles that C into an ARM64 Mach-O executable. Generated game
code comes from your verified files during the build. The repository contains
the translator, handwritten runtime adapters and metadata rather than
decompiled EA functions.

This is ahead-of-time binary translation, not a source-level rewrite. It keeps
the original 32-bit memory layout, register and flag state, x87 behavior and
calling conventions where the original code requires them. Native adapters
implement Win32, DirectInput and DirectSound calls. Direct3D 9 resources,
rendering state and shaders are translated to Metal. Cocoa supplies the
launcher and window, and CoreAudio supplies sound output. The game does not
run through Wine, Rosetta or a runtime x86 interpreter.

Full HQ combines handwritten native adaptations with ahead-of-time compilation
of the original supplied ASI modules. The build runs bounded headless native
initializers to derive finite code-patch states, then compiles guarded ARM64
variants. Original module writers perform those writes; preparation models
only the host interfaces needed to reach them without a live race or graphics
device. The original audio banks are also inspected at build time to prepare
native templates for their generated callbacks. An unknown code state stops
with a diagnostic and requires a native rebuild; it never falls back to
interpreting or executing x86 code.

The supported canonical runtime is reconstructed locally from the verified
HQ code image and official 1.3 resources. Its SHA-256 is
`80774c2e5d619b4f120b48d4462896fd504c263399d203a238769cffde1d253c`.
Standard and visuals-only modes use original shader resources. Full HQ uses
its selected original mod resources and compiled modules.
