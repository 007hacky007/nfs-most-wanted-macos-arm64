import XCTest
@testable import BuilderCore

final class DestinationTests: XCTestCase {
    var root: URL!
    let fm = FileManager.default

    override func setUpWithError() throws {
        root = fm.temporaryDirectory.appendingPathComponent("nfsmw-dest-\(UUID().uuidString)")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDown() {
        for dir in [root!, root.appendingPathComponent("dest")] {
            try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: dir.path)
        }
        try? fm.removeItem(at: root)
    }

    private func makeApp(at url: URL, marker: String, bundleID: String = gameBundleID) throws {
        try fm.createDirectory(at: url.appendingPathComponent("Contents"), withIntermediateDirectories: true)
        let plist = try PropertyListSerialization.data(fromPropertyList: ["CFBundleIdentifier": bundleID],
                                                       format: .xml, options: 0)
        try plist.write(to: url.appendingPathComponent("Contents/Info.plist"))
        try marker.write(to: url.appendingPathComponent("Contents/marker"), atomically: true, encoding: .utf8)
    }

    private func marker(_ app: URL) throws -> String {
        try String(contentsOf: app.appendingPathComponent("Contents/marker"), encoding: .utf8)
    }

    private func dest() throws -> URL {
        let dest = root.appendingPathComponent("dest")
        try fm.createDirectory(at: dest, withIntermediateDirectories: true)
        return dest
    }

    func testInstallReplacesExistingApp() throws {
        let dest = try dest()
        try makeApp(at: dest.appendingPathComponent("NFSMW.app"), marker: "old")
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new")
        let result = try installApp(built, into: dest, isRunning: { false })
        XCTAssertEqual(result.lastPathComponent, "NFSMW.app")
        XCTAssertEqual(try marker(result), "new")
        XCTAssertFalse(fm.fileExists(atPath: dest.appendingPathComponent(".NFSMW.app.installing").path))
    }

    func testFreshInstallAndStaleStagingCleaned() throws {
        let dest = try dest()
        try makeApp(at: dest.appendingPathComponent(".NFSMW.app.installing"), marker: "stale")
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new")
        let result = try installApp(built, into: dest, isRunning: { false })
        XCTAssertEqual(try marker(result), "new")
        XCTAssertFalse(fm.fileExists(atPath: dest.appendingPathComponent(".NFSMW.app.installing").path))
    }

    func testRunningGameIsNotReplaced() throws {
        let dest = try dest()
        try makeApp(at: dest.appendingPathComponent("NFSMW.app"), marker: "old")
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new")
        XCTAssertThrowsError(try installApp(built, into: dest, isRunning: { true })) { error in
            XCTAssertEqual(error.localizedDescription, "Quit NFSMW first, then try again.")
        }
        XCTAssertEqual(try marker(dest.appendingPathComponent("NFSMW.app")), "old")
        XCTAssertEqual(try marker(built), "new")
    }

    func testUnrelatedAppIsNeverReplaced() throws {
        let dest = try dest()
        let other = dest.appendingPathComponent("NFSMW.app")
        try makeApp(at: other, marker: "theirs", bundleID: "com.example.other")
        XCTAssertEqual(destinationCheck(dest), .blocked(unrelatedAppMessage))
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new")
        XCTAssertThrowsError(try installApp(built, into: dest, isRunning: { false })) { error in
            XCTAssertEqual(error.localizedDescription, unrelatedAppMessage)
        }
        XCTAssertEqual(try marker(other), "theirs")
        try fm.removeItem(at: other.appendingPathComponent("Contents/Info.plist"))
        XCTAssertEqual(destinationCheck(dest), .blocked(unrelatedAppMessage))
        try fm.removeItem(at: other)
        try fm.createSymbolicLink(at: other, withDestinationURL: root.appendingPathComponent("nowhere"))
        XCTAssertEqual(destinationCheck(dest), .blocked(unrelatedAppMessage))
    }

    func testSameVolumeInstallMovesInsteadOfCopying() throws {
        let dest = try dest()
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new")
        let inode = try fm.attributesOfItem(atPath: built.path)[.systemFileNumber] as? Int
        var reported = false
        let result = try installApp(built, into: dest, isRunning: { false }, progress: { _, _ in reported = true })
        XCTAssertFalse(fm.fileExists(atPath: built.path))
        XCTAssertEqual(try fm.attributesOfItem(atPath: result.path)[.systemFileNumber] as? Int, inode)
        XCTAssertFalse(reported)
    }

    func testCopyWithProgressReportsBytes() throws {
        let source = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: source, marker: String(repeating: "x", count: 100_000))
        var seen: [(Int64, Int64)] = []
        try copyWithProgress(source, to: root.appendingPathComponent("copy.app"), progress: { seen.append(($0, $1)) })
        XCTAssertEqual(try marker(root.appendingPathComponent("copy.app")), try marker(source))
        XCTAssertEqual(seen.first?.0, 0)
        XCTAssertEqual(seen.last?.0, seen.last?.1)
    }

    func testFailedInstallLeavesNoStagingAndKeepsOldApp() throws {
        let dest = try dest()
        try makeApp(at: dest.appendingPathComponent("NFSMW.app"), marker: "old")
        let missing = root.appendingPathComponent("nope/NFSMW.app")
        XCTAssertThrowsError(try installApp(missing, into: dest, isRunning: { false })) { error in
            XCTAssertEqual(error.localizedDescription, "The built app is missing. Build again.")
        }
        XCTAssertEqual(try marker(dest.appendingPathComponent("NFSMW.app")), "old")
        XCTAssertFalse(fm.fileExists(atPath: dest.appendingPathComponent(".NFSMW.app.installing").path))
    }

    func testWrongBuiltBundleIsRefusedAndMovedBack() throws {
        let dest = try dest()
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new", bundleID: "com.example.wrong")
        XCTAssertThrowsError(try installApp(built, into: dest, isRunning: { false })) { error in
            XCTAssertEqual(error.localizedDescription, "The built app is incomplete. Build again.")
        }
        XCTAssertEqual(try marker(built), "new")
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: dest.path), [])
    }

    func testStagingFailureGivesPlainErrorAndKeepsOldApp() throws {
        let dest = try dest()
        try makeApp(at: dest.appendingPathComponent("NFSMW.app"), marker: "old")
        let built = root.appendingPathComponent("built/NFSMW.app")
        try makeApp(at: built, marker: "new")
        try fm.setAttributes([.posixPermissions: 0o555], ofItemAtPath: dest.path)
        XCTAssertThrowsError(try installApp(built, into: dest, isRunning: { false })) { error in
            XCTAssertEqual(error.localizedDescription, "Could not install NFSMW into dest. Choose another folder and try again.")
            XCTAssertNotNil((error as? InstallError)?.details)
        }
        XCTAssertEqual(try marker(dest.appendingPathComponent("NFSMW.app")), "old")
        XCTAssertEqual(try marker(built), "new")
    }

    func testUnwritableDestinationIsRed() throws {
        try fm.setAttributes([.posixPermissions: 0o555], ofItemAtPath: root.path)
        XCTAssertEqual(destinationCheck(root), .blocked("Choose a folder you can write to"))
    }

    func testMissingDestinationIsRedAndWritableIsReady() throws {
        XCTAssertEqual(destinationCheck(root.appendingPathComponent("missing")), .blocked("Choose a folder you can write to"))
        XCTAssertTrue(destinationCheck(root).isReady)
        try makeApp(at: root.appendingPathComponent("NFSMW.app"), marker: "ours")
        XCTAssertTrue(destinationCheck(root).isReady)
        XCTAssertTrue(sameVolume(root, root.appendingPathComponent("not yet/there")))
    }
}
