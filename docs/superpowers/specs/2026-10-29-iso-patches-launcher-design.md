# ISO installation, patches and launcher

The supplied four Black Edition ISO discs in `game_backup2` replace the raw-disc backup as the primary installation source. Extract their ZIP payloads without executing Windows installers. Decode and verify all seven official 1.3 replacements, preserving the official executable. The HQ installer contains an unprotected executable whose game code, imports and main data sections match the existing native target. Its shader resources differ, so reconstruct the supported Standard runtime using the official resources and verify the complete image hash. Do not execute the protected Windows entry point.

The native macOS launcher remembers the installation folder and resolution and offers Standard, HQ visuals only, and HQ full mod modes. This three-mode choice was requested explicitly. Each mode uses separate save and registry folders. Changing mode must not overwrite the base game, backups or other modes' files.

Widescreen support uses native guest hooks and Metal runtime handling. Preserve sound, music, videos and cutscenes, including startup movies. Keep the supplied Windows plugins as installation inputs and provenance; copying an ASI does not make its behavior native.

HQ visuals uses compatible visual assets while retaining the standard gameplay database and car list. HQ full includes the supplied gameplay, cars and native equivalents of the enabled code mods. The user explicitly requested full mod behavior as well as the visuals-only choice. A full mode must not claim readiness based only on successful extraction or a checked launcher control. Track unsupported hooks and test actual races, videos and audio before enabling it.

Use the current Python installer and Objective-C/C runtime. Keep extracted and generated proprietary data ignored. New source and documentation must not contain personal paths or identifiers. Keep all backups and the existing working installation intact during verification.
