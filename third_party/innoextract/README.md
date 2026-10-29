# Native HQ extraction

The HQ 1.20.9 installer uses Inno Setup 6.6.1. No Windows executable is run.
`tools/extract_hq.py` invokes a native innoextract binary and verifies its exit status.
The installer ZIP is read locally. The verified Microsoft D3DX9_26 cabinet
can supply a missing DLL; its Windows installer is never executed.

For the complete app build, use `./build.sh` as described in the repository
README. The commands below are internal extraction tools for development.

Build prerequisites: Python 3.12+, CMake, a C++ compiler, Boost and liblzma.
On Apple Silicon these can be supplied by the Xcode command-line tools and Homebrew.

Build with the already downloaded, checksum-pinned source archive:

```sh
python3 tools/build_hq_extractor.py --source-archive out/hq-extract/innoextract-pr214.tar.gz
```

To explicitly download the source before building, use:

```sh
python3 tools/build_hq_extractor.py --download
```

Extract the supplied local package into a new directory:

```sh
python3 tools/extract_hq.py game_backup2/patches/MW_HQ_1.20.9.zip out/hq-source
```

The build cache lives in ignored `out/tools/hq-extractor`. Extraction needs temporary
space for the installer slices, the decoded payload and normalized files. Existing
destinations are refused. Every published file and each installer input gets a SHA-256
in `.hq-manifest.json`. Identical numbered copies collapse to one canonical path;
different optional copies retain their suffixes and are listed under `variants`.
Component suffix backslashes are encoded as hyphens, for example `#lang-en`.
A caller must select a variant explicitly; extraction never chooses a soundtrack or language.

## Source and local patches

Source: [innoextract PR 214](https://github.com/dscharrer/innoextract/pull/214),
commit `8f317ad`, archive
[download](https://codeload.github.com/psi29a/innoextract/tar.gz/8f317ad).
SHA-256: `b9d6fadd35f3904d028174d7d041fc7e28af77c082ff10a2407e982e6419dead`.
The upstream [license](LICENSE) is preserved here and in the downloaded source.
No third-party implementation source or executable is committed.

The builder marks and applies three local fixes:

- Recognize `idskb32` slice magic and consume the 64-bit size field. Its header is
  16 bytes. The old 12-byte reader fed four header bytes into LZMA when opening
  the second slice, which caused a decompression failure. Slice sizes above 4 GiB
  are explicitly refused by this implementation.
- Bound the slice magic search loop by the number of known signatures.
- Print all 32 SHA-256 bytes. Upstream's display loop printed only the first 20;
  its extraction checksum validation already compared all 32 bytes.

The slice format is defined by Inno Setup's
[6.6.1 source](https://github.com/jrsoftware/issrc/blob/is-6_6_1/Projects/Src/Shared.Struct.pas).
The supplied slices were verified to start with `idskb32` and their 64-bit file sizes.

## Separate game data modes

`tools.hq_variants.build_variants(base, hq_source)` takes an installed standard game
and the normalized HQ source. It writes `.nfsmw/runtime.exe`, `.nfsmw/visuals`,
`.nfsmw/full` and `.nfsmw/variants.json` inside that game directory. Existing variant
directories are refused. Source file hashes and the HQ runtime fingerprint are checked.
The standard executable and data remain intact.

Visuals keeps standard gameplay, car registration, audio, videos and original shaders.
It applies existing-car visual files, world files and texture packs. Full selects English,
modern shaders, Xbox 360 lighting, standard difficulty and the original playlist at the
HQ package's higher audio quality. Intro movies and cinematics remain enabled.
The modern preset intentionally keeps the original carnormalmap shader, matching the
installer's explicit copy list. Full also selects the lighting-specific GlobalB.lzc and
VLT/gameplay files; the common GLOBALB.BUN alone does not register the added cars.

Both modes are available after installation. The launcher also requires a
build containing the native HQ modules before enabling Full. The public builder
prepares those modules and their guarded native game-code variants locally.

Standard and Visual use `tools/runtime_image.py` to reconstruct the supported
`80774c2e...` runtime from the fingerprinted HQ code image and official 1.3 resource
section. The output is byte-for-byte identical to the previously supported runtime.
All 33 resource payloads match the official game. Raw HQ contains modified car, sky
and screen-filter shader resources and is retained only in the unavailable Full tree.
