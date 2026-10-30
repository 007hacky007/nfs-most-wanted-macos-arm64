# Background performance measurements

The runtime supports profiling without a visible game window or audio. Invoke
the engine directly with an explicit prepared game executable, `NOFOCUS=2`,
`NFSFULL=0`, `NFSU2_BACKGROUND=run` and `NFSU2_MUTE=1`. Use a disposable
`NFSMW_SAVEDIR` and the existing command-file or scripted-input interface.
This bypasses the launcher. The transparent window ignores mouse input and
does not activate the game. Captures come from the game renderer, not the desktop.

## Indexed patch lookup, 2026-10-30

Indirect calls into translated DLLs previously searched the runtime patch list
linearly. The prepared HQ build registers 104 routes, including when its visual
assets are selected without the full mod. Samples from an HQ visuals race
identified this scan as a CPU cost. A fixed index now resolves these addresses;
patch replacement, NULL handlers and game-text dispatch retain their behavior.

The comparison used an Apple M1 Pro with 32 GB RAM, HQ visuals at 1920x1080,
the stock IS300, Seaside & Power Station Sprint and three opponents. Both builds
used the same game files, disposable profile and scripted navigation. The player
car remained at the starting line. Frames 9500 through 12000 supplied about
30 seconds per run, after loading and the countdown. Both runs had profiling
enabled, nominal thermal state and more than 98% of process CPU time on
performance cores.

| Measurement | Before | After |
| --- | ---: | ---: |
| Mean guest CPU time per frame | 6.86 ms | 5.83 ms |
| Guest CPU time, p95 | 7.52 ms | 6.52 ms |
| Guest CPU time, p99 | 8.26 ms | 7.13 ms |
| Mean Metal encoding time | 0.565 ms | 0.582 ms |
| Mean GPU time | 1.93 ms | 1.97 ms |
| Mean draw calls per frame | 1030.4 | 1029.4 |
| Mean interval between submitted frames | 12.40 ms | 11.98 ms |
| Submitted-frame interval, p99 | 18.93 ms | 19.34 ms |

Guest CPU cost fell about 15%. Submitted-frame throughput increased about
3.5%, while GPU cost stayed similar. The interval tail did not improve in this
pair. A separate 104-patch miss-lookup benchmark measured 40.35 ns before and
3.75 ns after. That isolated speedup does not translate directly into game FPS.

These are one paired run and a lookup benchmark, recorded while the computer
was also in use. A transparent window reports submitted frames rather than
visible display frames. Profiling overhead has not been quantified with an
unprofiled driving comparison. These results do not establish sustained 60 FPS
in active driving, Full HQ or 4K performance. Foreground gameplay validation
remains deferred until the computer is available for it.

The dispatch regression checks cover capacity, explicit overflow, game and DLL
replacement, collision wrap-around, zero addresses and NULL replacements. The
full suite passed 353 tests, with 32 skipped. Raw traces and game captures stay
in ignored local output directories.
