import Foundation

/// The `--progress` step ids of tools/build_app.py in order, with progress bar weights (sum 100).
/// Measured end-to-end on an M1 Pro with the downloads cached (21 minutes): hq 248 s, bootstrap
/// 207 s, two runtime rounds 380 s, final 189 s, package 83 s, translate 59 s, the rest under a
/// minute each. `downloads` stands for the 3.34 GB first download at a typical connection.
public let buildSteps: [(id: String, weight: Double)] = [
    ("check", 1), ("downloads", 15), ("tools", 1), ("game", 2), ("patches", 1), ("hq", 17), ("variants", 2),
    ("translate", 4), ("audio", 1), ("modules", 3), ("bootstrap", 14), ("runtime", 22), ("final", 12),
    ("package", 5),
]

/// What the user reads for each step.
public let buildStepNames: [String: String] = [
    "check": "Checking your game copy",
    "downloads": "Downloading patches and Most Wanted HQ (3.36 GB)",
    "tools": "Preparing the extraction tools",
    "game": "Copying and checking all game files",
    "patches": "Applying the official 1.3 patch, D3DX and WidescreenFix",
    "hq": "Unpacking Most Wanted HQ",
    "variants": "Preparing Standard, HQ visual and Full HQ data",
    "translate": "Translating the game to C",
    "audio": "Preparing native audio callbacks",
    "modules": "Generating the six original runtime modules",
    "bootstrap": "First native build and module start-up",
    "runtime": "Finding the remaining code states",
    "final": "Final native build and verification run",
    "package": "Packaging and signing NFSMW.app",
]

private var totalWeight: Double { buildSteps.reduce(0) { $0 + $1.weight } }

/// Fraction (0...1) of the work done when `stepID` begins; nil for an unknown step.
public func progressFraction(atStart stepID: String) -> Double? {
    guard let index = buildSteps.firstIndex(where: { $0.id == stepID }) else { return nil }
    return buildSteps[..<index].reduce(0) { $0 + $1.weight } / totalWeight
}

/// Fraction (0...1) of the work done `within` (0...1) of the way through `step`.
public func progressFraction(step: String, within: Double) -> Double? {
    guard let start = progressFraction(atStart: step),
          let weight = buildSteps.first(where: { $0.id == step })?.weight else { return nil }
    return start + weight * min(max(within, 0), 1) / totalWeight
}
