import Foundation

public let defaultDestination = URL(fileURLWithPath: "/Applications")
/// CFBundleIdentifier of the game NFSMW.app (tools/package_app.py).
public let gameBundleID = "local.nfsmw.native"
public let unrelatedAppMessage = "There is a different NFSMW.app in this folder. Choose another folder."

public struct InstallError: LocalizedError {
    public let message: String
    /// Underlying error text, for the log.
    public var details: String? = nil
    public var errorDescription: String? { message }

    public init(message: String, details: String? = nil) {
        self.message = message
        self.details = details
    }
}

func bundleIdentifier(of app: URL) -> String? {
    guard let data = try? Data(contentsOf: app.appendingPathComponent("Contents/Info.plist")),
          let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
    else { return nil }
    return plist["CFBundleIdentifier"] as? String
}

/// True when `directory/NFSMW.app` exists but is not ours, so it must never be replaced.
func hasUnrelatedApp(_ directory: URL) -> Bool {
    let target = directory.appendingPathComponent("NFSMW.app")
    let exists = (try? target.checkResourceIsReachable()) == true
        || (try? FileManager.default.destinationOfSymbolicLink(atPath: target.path)) != nil
    return exists && bundleIdentifier(of: target) != gameBundleID
}

public func destinationCheck(_ directory: URL) -> CheckState {
    var isDir: ObjCBool = false
    let exists = FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDir)
    guard exists, isDir.boolValue, FileManager.default.isWritableFile(atPath: directory.path) else {
        return .blocked("Choose a folder you can write to")
    }
    if hasUnrelatedApp(directory) { return .blocked(unrelatedAppMessage) }
    return .ready(directory.path)
}

func volumeIdentifier(_ url: URL) -> NSObject? {
    var probe = url
    while !FileManager.default.fileExists(atPath: probe.path) && probe.path != "/" {
        probe = probe.deletingLastPathComponent()
    }
    return (try? probe.resourceValues(forKeys: [.volumeIdentifierKey]))?.volumeIdentifier as? NSObject
}

public func sameVolume(_ a: URL, _ b: URL) -> Bool {
    guard let left = volumeIdentifier(a), let right = volumeIdentifier(b) else { return false }
    return left.isEqual(right)
}

/// Copies `source` to `target` file by file, reporting (copied, total) bytes.
func copyWithProgress(_ source: URL, to target: URL, progress: ((Int64, Int64) -> Void)?) throws {
    let fm = FileManager.default
    guard let progress = progress else { return try fm.copyItem(at: source, to: target) }
    let total = allocatedSize(of: source)
    var copied: Int64 = 0
    progress(0, total)
    try fm.createDirectory(at: target, withIntermediateDirectories: false)
    let keys: [URLResourceKey] = [.isDirectoryKey, .isSymbolicLinkKey, .totalFileAllocatedSizeKey]
    guard let walker = fm.enumerator(at: source, includingPropertiesForKeys: keys) else { return }
    let base = source.standardizedFileURL.path
    for case let item as URL in walker {
        let relative = String(item.standardizedFileURL.path.dropFirst(base.count + 1))
        let destination = target.appendingPathComponent(relative)
        let values = try item.resourceValues(forKeys: Set(keys))
        if values.isDirectory == true && values.isSymbolicLink != true {
            try fm.createDirectory(at: destination, withIntermediateDirectories: true)
        } else {
            try fm.copyItem(at: item, to: destination)
            copied += Int64(values.totalFileAllocatedSize ?? 0)
            progress(copied, total)
        }
    }
}

/// Puts the built NFSMW.app into `directory`. On the same volume the build is moved (instant,
/// no extra space); on another volume it is copied with byte progress. It is staged next to the
/// final location first and swapped in, so an older NFSMW.app survives any failure before the
/// swap. An app with another bundle id, or one that is running, is never replaced.
public func installApp(_ built: URL, into directory: URL, isRunning: () -> Bool,
                       progress: ((Int64, Int64) -> Void)? = nil) throws -> URL {
    if isRunning() { throw InstallError(message: "Quit NFSMW first, then try again.") }
    if hasUnrelatedApp(directory) { throw InstallError(message: unrelatedAppMessage) }
    let fm = FileManager.default
    let target = directory.appendingPathComponent("NFSMW.app")
    let staging = directory.appendingPathComponent(".NFSMW.app.installing")
    var moved = false
    do {
        if (try? staging.checkResourceIsReachable()) == true { try fm.removeItem(at: staging) }
        guard fm.fileExists(atPath: built.appendingPathComponent("Contents/Info.plist").path) else {
            throw InstallError(message: "The built app is missing. Build again.")
        }
        if sameVolume(built, directory) {
            try fm.moveItem(at: built, to: staging)
            moved = true
        } else {
            try copyWithProgress(built, to: staging, progress: progress)
        }
        try removeQuarantine(at: staging)
        guard bundleIdentifier(of: staging) == gameBundleID else {
            throw InstallError(message: "The built app is incomplete. Build again.")
        }
        var final = target
        if (try? target.checkResourceIsReachable()) == true {
            final = try fm.replaceItemAt(target, withItemAt: staging) ?? target
        } else {
            try fm.moveItem(at: staging, to: target)
        }
        guard bundleIdentifier(of: final) == gameBundleID else {
            throw InstallError(message: "The installed app is incomplete.")
        }
        return final
    } catch {
        // A moved build goes back where it was, so Try again does not need a new 15 GB build.
        if !(moved && (try? fm.moveItem(at: staging, to: built)) != nil) {
            try? fm.removeItem(at: staging)
        }
        if let error = error as? InstallError, error.details == nil, error.message.hasPrefix("The built app") {
            throw error
        }
        throw InstallError(
            message: "Could not install NFSMW into \(directory.lastPathComponent). Choose another folder and try again.",
            details: String(describing: error))
    }
}
