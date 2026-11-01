import Foundation

/// Info.plist key with the NFSMW Builder version that built an app (tools/package_app.py).
public let builderVersionKey = "NFSBuilderVersion"

/// True for an NFSMW.app built by this project: a real folder (not a symlink) with our bundle id.
public func isGameApp(_ app: URL) -> Bool {
    var isDir: ObjCBool = false
    guard (try? FileManager.default.destinationOfSymbolicLink(atPath: app.path)) == nil,
          FileManager.default.fileExists(atPath: app.path, isDirectory: &isDir), isDir.boolValue
    else { return false }
    return bundleIdentifier(of: app) == gameBundleID
}

/// The NFSMW.app an update starts from: the one in the saved destination, else the one in
/// /Applications. It is only ever read; whether its game can be reused is the pipeline's
/// usual game check (tools/game_sources.py accepts an NFSMW.app as a game copy).
public func findExistingApp(destination: URL, fallback: URL = defaultDestination) -> URL? {
    for directory in [destination, fallback] {
        let app = directory.appendingPathComponent("NFSMW.app")
        if isGameApp(app) { return app }
    }
    return nil
}

/// The Builder version stamped into an app, or nil (a Terminal build, or a build from before stamps).
public func builderVersion(of app: URL) -> String? {
    guard let data = try? Data(contentsOf: app.appendingPathComponent("Contents/Info.plist")),
          let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
          let version = plist[builderVersionKey] as? String, !version.isEmpty
    else { return nil }
    return version
}

/// The build button: "Update NFSMW.app (old -> new)" when the build replaces the app it reads
/// the game from and that app's version is known, "Update NFSMW.app" without a known version,
/// else "Build NFSMW.app".
public func buildButtonTitle(updating: Bool, oldVersion: String?, newVersion: String) -> String {
    guard updating else { return "Build NFSMW.app" }
    guard let old = oldVersion else { return "Update NFSMW.app" }
    return "Update NFSMW.app (\(old) -> \(newVersion))"
}
