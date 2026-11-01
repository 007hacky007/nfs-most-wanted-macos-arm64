import Foundation

public enum CheckID: CaseIterable {
    case mac, commandLineTools, buildTools, downloads, gameCopy, destination, diskSpace
}

/// Grey (checking), green (ready), amber (handled during the build), red (blocked).
public enum CheckState: Equatable {
    case checking(String)
    case ready(String)
    case automatic(String)
    case blocked(String)

    public var isReady: Bool {
        if case .ready = self { return true }
        return false
    }

    public var message: String {
        switch self {
        case let .checking(text), let .ready(text), let .automatic(text), let .blocked(text): return text
        }
    }
}

/// Build is allowed when every row is green or amber.
public func canBuild(_ states: [CheckID: CheckState]) -> Bool {
    CheckID.allCases.allSatisfy { id in
        switch states[id] {
        case .ready?, .automatic?: return true
        default: return false
        }
    }
}

public func macCheck(isAppleSilicon: Bool, version: OperatingSystemVersion) -> CheckState {
    guard isAppleSilicon else {
        return .blocked("NFSMW Builder needs a Mac with Apple Silicon")
    }
    guard version.majorVersion >= 12 else {
        return .blocked("NFSMW Builder needs macOS 12 or newer. On macOS 11, build from Terminal.")
    }
    return .ready("Apple Silicon, macOS \(version.majorVersion).\(version.minorVersion)")
}

/// Peak space the build uses in its workspace, plus the download cache. Measured end-to-end:
/// 32.7 GB in the workspace while NFSMW.app is packaged, plus the 3.4 GB cache, plus room for other
/// programs writing to the same disk during the 25 minutes.
public let requiredWorkspaceBytes: Int64 = 45_000_000_000
/// The finished NFSMW.app, which holds your game files and the HQ data (measured 16.0 GB, plus margin).
public let appBytes: Int64 = 18_000_000_000

public func gigabytes(_ bytes: Int64) -> String {
    String(format: "%.1f GB", Double(bytes) / 1_000_000_000)
}

/// "612 MB", "32.7 GB": sizes as Finder shows them, also for leftovers well under a gigabyte.
public func sizeText(_ bytes: Int64) -> String {
    ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
}

/// The texts of the controls that delete files.
///
/// Temporary files are what `removeBuildFiles` deletes: everything a build wrote in this
/// version's workspace (out/, gen/ and the rest: the extracted and prepared game files, the
/// translated and compiled code, the step logs and an NFSMW.app that was built but not
/// installed). It keeps the bundled build scripts, their .venv packages, the private Python,
/// the download cache, an installed NFSMW.app, the player's game copy, saves and settings.
///
/// Downloads are the Builder's own download cache (`BuilderPaths.cache`): the official 1.3
/// patch, WidescreenFix and Most Wanted HQ, also a partial download. NFSMW.app holds all it
/// needs, so it keeps working without them.
public enum CleanupText {
    public static let deleting = "Deleting temporary files..."
    public static let deletingOld = "Deleting old temporary files..."

    public static func button(bytes: Int64) -> String { "Delete temporary files (\(sizeText(bytes)))" }

    /// After the automatic delete that follows a successful install.
    public static func deleted(freed: Int64) -> String {
        "Temporary files deleted, \(sizeText(freed)) freed. NFSMW.app and your game are unchanged; "
            + "Python and the downloads are kept for the next build."
    }

    /// The first caption line under a delete button: exactly where it deletes, with ~ for the
    /// home folder so no user name shows.
    static func tilde(_ url: URL) -> String { (url.path as NSString).abbreviatingWithTildeInPath }

    /// `workspace` is `BuilderPaths.workspace(version:)`; its build scripts and .venv stay.
    public static func deletesLine(workspace: URL) -> String {
        "Deletes the build's files in \(tilde(workspace)); the build scripts and Python packages there stay"
    }

    /// For the leftovers of a cancelled, failed or not installed build (checklist and failure screen).
    public static let leftoverCaption = "Only what that build left in the Builder's own work folder, "
        + "including an NFSMW.app it built but did not install, and its step logs. "
        + "An installed NFSMW.app, your game copy, saves, settings, Python and the downloads stay."

    /// `cache` is `BuilderPaths.cache`, which the Builder empties.
    public static func downloadsDeletesLine(cache: URL) -> String { "Deletes \(tilde(cache))" }

    public static func downloadsButton(bytes: Int64) -> String { "Delete downloads (\(sizeText(bytes)))" }

    public static func downloadsCaption(bytes: Int64) -> String {
        "The official patch, WidescreenFix and Most Wanted HQ. NFSMW.app does not need them and keeps working; "
            + "the next build downloads them again, \(sizeText(bytes))."
    }

    public static let downloadsDeleted = "Downloads deleted. NFSMW.app is unchanged; the next build downloads them again."
}

/// `cachedBytes` are downloads already in the cache, which the build does not need again.
/// On the same volume the finished app is moved, not copied, so it needs no extra space.
public func diskSpaceCheck(workspaceAvailable: Int64, workspaceVolume: String,
                           destinationAvailable: Int64, destinationVolume: String,
                           sameVolume: Bool, cachedBytes: Int64) -> CheckState {
    let workspaceNeed = max(requiredWorkspaceBytes - max(cachedBytes, 0), 0)
    if workspaceAvailable < workspaceNeed {
        return .blocked("Only \(gigabytes(workspaceAvailable)) free on \(workspaceVolume), "
            + "\(gigabytes(workspaceNeed)) needed during the build")
    }
    if !sameVolume && destinationAvailable < appBytes {
        return .blocked("Only \(gigabytes(destinationAvailable)) free on \(destinationVolume), "
            + "\(gigabytes(appBytes)) needed for NFSMW.app")
    }
    return .ready("\(gigabytes(workspaceAvailable)) free on \(workspaceVolume)")
}

/// Pipeline messages name the build's Try again button ("Click Try again ...", "... click Try
/// again."). Where another button does the job, such as Download now on the Downloads row, the
/// sentence names that button instead, in either case.
public func naming(button: String, in message: String) -> String {
    message.replacingOccurrences(of: "Click Try again", with: "Click \(button)")
        .replacingOccurrences(of: "click Try again", with: "click \(button)")
}
