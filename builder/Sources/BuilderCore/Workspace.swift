import Foundation

/// The top-level entries of the bundled build sources. tools/make_builder.py bundles the tracked
/// files under the same entries (a test keeps both lists equal); `helpers` holds the CI-built
/// innoextract and RTPatch decoder.
public let bundledSourceEntries = ["build.sh", "gen.sh", "requirements.txt", "LICENSE", "tools", "runtime",
                                   "third_party", "helpers"]

public struct BuilderPaths {
    public let support: URL
    public let cache: URL

    public init(support: URL = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Application Support/NFSMW Builder"),
                cache: URL = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Caches/NFSMW/downloads")) {
        self.support = support
        self.cache = cache
    }

    public var python: URL { support.appendingPathComponent("python") }
    public var pythonExecutable: URL { python.appendingPathComponent("bin/python3") }

    public func workspace(version: String) -> URL {
        support.appendingPathComponent(version)
    }

    public func venvPython(version: String) -> URL {
        workspace(version: version).appendingPathComponent(".venv/bin/python")
    }

    public func helpers(version: String) -> URL {
        workspace(version: version).appendingPathComponent("helpers")
    }

    /// The finished app inside the workspace, before it is installed.
    public func builtApp(version: String) -> URL {
        workspace(version: version).appendingPathComponent("out/NFSMW.app")
    }
}

private let versionMarker = ".builder-version"

/// Copies the pipeline sources into `destination`. A destination whose marker matches
/// `version` and that holds every bundled entry of `sources` is left alone; anything else is
/// replaced atomically. The workspace and the support folder are excluded from Time Machine.
public func prepareWorkspace(sources: URL, destination: URL, version: String) throws {
    let fm = FileManager.default
    let parent = destination.deletingLastPathComponent()
    try fm.createDirectory(at: parent, withIntermediateDirectories: true)
    try excludeFromBackup(parent)
    let marker = destination.appendingPathComponent(versionMarker)
    if let current = try? String(contentsOf: marker, encoding: .utf8), current == version,
       bundledSourceEntries.allSatisfy({ !fm.fileExists(atPath: sources.appendingPathComponent($0).path)
           || fm.fileExists(atPath: destination.appendingPathComponent($0).path) }) {
        try excludeFromBackup(destination)
        return
    }

    let temp = parent.appendingPathComponent(".\(destination.lastPathComponent).tmp-\(UUID().uuidString)")
    do {
        try fm.createDirectory(at: temp, withIntermediateDirectories: true)
        for entry in bundledSourceEntries {
            let from = sources.appendingPathComponent(entry)
            guard fm.fileExists(atPath: from.path) else { continue }
            try fm.copyItem(at: from, to: temp.appendingPathComponent(entry))
        }
        try removePycache(in: temp)
        try removeQuarantine(at: temp)
        try version.write(to: temp.appendingPathComponent(versionMarker), atomically: true, encoding: .utf8)
        try excludeFromBackup(temp)
        let old = fm.fileExists(atPath: destination.path) ? try moveToTrash(destination) : nil
        try fm.moveItem(at: temp, to: destination)
        if let old = old { try? fm.removeItem(at: old) }
    } catch {
        try? fm.removeItem(at: temp)
        throw error
    }
}

public func excludeFromBackup(_ url: URL) throws {
    var url = url
    var values = URLResourceValues()
    values.isExcludedFromBackup = true
    try url.setResourceValues(values)
}

/// Renames `url` to a hidden `.trash-<uuid>` sibling in one atomic step and returns that
/// location. A quit while the caller deletes it then never leaves a half-removed directory
/// under the real name; `sweepOldWorkspaces` deletes the rest on the next start.
public func moveToTrash(_ url: URL) throws -> URL {
    let trash = url.deletingLastPathComponent().appendingPathComponent(".trash-\(UUID().uuidString)")
    try FileManager.default.moveItem(at: url, to: trash)
    return trash
}

private func removePycache(in root: URL) throws {
    let fm = FileManager.default
    guard let walker = fm.enumerator(at: root, includingPropertiesForKeys: nil) else { return }
    var found: [URL] = []
    for case let url as URL in walker where url.lastPathComponent == "__pycache__" {
        found.append(url)
        walker.skipDescendants()
    }
    for url in found { try fm.removeItem(at: url) }
}

/// Allocated bytes of everything below `url` (0 when it does not exist).
public func allocatedSize(of url: URL) -> Int64 {
    let keys: [URLResourceKey] = [.totalFileAllocatedSizeKey, .isRegularFileKey]
    if let values = try? url.resourceValues(forKeys: Set(keys)), values.isRegularFile == true {
        return Int64(values.totalFileAllocatedSize ?? 0)
    }
    guard let walker = FileManager.default.enumerator(at: url, includingPropertiesForKeys: keys) else { return 0 }
    var total: Int64 = 0
    for case let item as URL in walker {
        guard let values = try? item.resourceValues(forKeys: Set(keys)), values.isRegularFile == true else { continue }
        total += Int64(values.totalFileAllocatedSize ?? 0)
    }
    return total
}

/// True while a build in that workspace holds its lock (tools/build_app.py takes out/app-build.lock).
public func workspaceIsLocked(_ workspace: URL) -> Bool {
    let lock = workspace.appendingPathComponent("out/app-build.lock")
    let fd = open(lock.path, O_RDONLY | O_NOFOLLOW)
    guard fd >= 0 else { return false }
    defer { close(fd) }
    if flock(fd, LOCK_EX | LOCK_NB) != 0 { return errno == EWOULDBLOCK }
    flock(fd, LOCK_UN)
    return false
}

/// Deletes what other Builder versions and interrupted work left in the support folder:
/// workspaces whose `.builder-version` names another version, `.trash-*` directories and
/// `.<name>.tmp-*` copies. Never the private Python, folders without a marker, or a workspace
/// whose build lock is held. Call it on start, before anything else uses the folder.
/// Returns the bytes freed.
@discardableResult
public func sweepOldWorkspaces(_ paths: BuilderPaths, keeping version: String,
                               isLocked: (URL) -> Bool = workspaceIsLocked) -> Int64 {
    let fm = FileManager.default
    var freed: Int64 = 0
    for name in (try? fm.contentsOfDirectory(atPath: paths.support.path)) ?? [] where name != paths.python.lastPathComponent {
        let dir = paths.support.appendingPathComponent(name)
        let leftover = name.hasPrefix(".trash-") || (name.hasPrefix(".") && name.contains(".tmp-"))
        if !leftover {
            guard !name.hasPrefix("."), name != version,
                  let marker = try? String(contentsOf: dir.appendingPathComponent(versionMarker), encoding: .utf8),
                  marker != version, !isLocked(dir) else { continue }
        }
        let size = allocatedSize(of: dir)
        guard let trash = leftover ? dir : try? moveToTrash(dir) else { continue }
        if (try? fm.removeItem(at: trash)) != nil { freed += size }
    }
    return freed
}

/// Removes what a build left in the workspace (out/, gen/ and anything else the pipeline wrote),
/// keeping the bundled sources, the .venv packages and the version marker, so the next build
/// needs no setup. Each item is renamed aside into the support folder first, so a quit during
/// the slow delete leaves only a `.trash-*` folder that the next start sweeps. Returns bytes freed.
@discardableResult
public func removeBuildFiles(_ paths: BuilderPaths, version: String) -> Int64 {
    let fm = FileManager.default
    let workspace = paths.workspace(version: version)
    let keep = Set(bundledSourceEntries + [".venv", versionMarker])
    var freed: Int64 = 0
    for name in (try? fm.contentsOfDirectory(atPath: workspace.path)) ?? [] where !keep.contains(name) {
        let item = workspace.appendingPathComponent(name)
        let size = allocatedSize(of: item)
        let trash = paths.support.appendingPathComponent(".trash-\(UUID().uuidString)")
        guard (try? fm.moveItem(at: item, to: trash)) != nil else { continue }
        if (try? fm.removeItem(at: trash)) != nil { freed += size }
    }
    return freed
}

/// Bytes `removeBuildFiles` would free.
public func buildFilesSize(_ paths: BuilderPaths, version: String) -> Int64 {
    let workspace = paths.workspace(version: version)
    let keep = Set(bundledSourceEntries + [".venv", versionMarker])
    return ((try? FileManager.default.contentsOfDirectory(atPath: workspace.path)) ?? [])
        .filter { !keep.contains($0) }
        .reduce(0) { $0 + allocatedSize(of: workspace.appendingPathComponent($1)) }
}

/// The helpers.json entries of a bundled helpers folder, or nil when the folder has none.
func helperDigests(_ directory: URL) -> [String: String]? {
    guard let data = try? Data(contentsOf: directory.appendingPathComponent("helpers.json")),
          let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
    var result: [String: String] = [:]
    for name in ["innoextract", "rtpatch-decode"] {
        guard let record = json[name] as? [String: Any], let sha = record["sha256"] as? String else { return nil }
        result[name] = sha
    }
    return result
}

public let incompleteBuilderMessage = "This copy of NFSMW Builder is incomplete. Download it again."

/// Ready when the private Python is installed, the workspace venv was built from the current
/// requirements.txt and every bundled helper matches helpers.json. `requireHelpers` is true
/// for a release bundle, where a missing helpers folder means a damaged download.
public func buildToolsCheck(paths: BuilderPaths, version: String, requireHelpers: Bool = false) -> CheckState {
    let workspace = paths.workspace(version: version)
    let helpers = paths.helpers(version: version)
    if FileManager.default.fileExists(atPath: helpers.path) || requireHelpers {
        guard let digests = helperDigests(helpers),
              digests.allSatisfy({ (try? sha256Hex(of: helpers.appendingPathComponent($0.key))) == $0.value })
        else { return .blocked(incompleteBuilderMessage) }
    }
    guard PythonRuntime.isInstalled(paths) else { return .blocked("about 90 MB download") }
    guard FileManager.default.fileExists(atPath: paths.venvPython(version: version).path),
          let requirements = try? sha256Hex(of: workspace.appendingPathComponent("requirements.txt")),
          let recorded = try? String(contentsOf: workspace.appendingPathComponent(".venv/.build-requirements-sha256"), encoding: .utf8),
          recorded.trimmingCharacters(in: .whitespacesAndNewlines) == requirements
    else { return .blocked("Packages need to be set up again (small download)") }
    return .ready("Installed")
}
