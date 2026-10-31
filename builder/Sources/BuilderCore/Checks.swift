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
/// 32.7 GB in the workspace while NFSMW.app is packaged, plus the 3.4 GB cache, with 10 percent margin.
public let requiredWorkspaceBytes: Int64 = 40_000_000_000
/// The finished NFSMW.app, which holds your game files and the HQ data (measured 16.0 GB, plus margin).
public let appBytes: Int64 = 18_000_000_000

public func gigabytes(_ bytes: Int64) -> String {
    String(format: "%.1f GB", Double(bytes) / 1_000_000_000)
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
