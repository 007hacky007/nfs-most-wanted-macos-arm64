import AppKit

/// True while the game (bundle id from tools/package_app.py) is running.
public func isNFSMWRunning() -> Bool {
    !NSRunningApplication.runningApplications(withBundleIdentifier: gameBundleID).isEmpty
}
