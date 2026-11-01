import XCTest
@testable import BuilderCore

final class ExistingAppTests: XCTestCase {
    var root: URL!
    let fm = FileManager.default

    override func setUpWithError() throws {
        root = fm.temporaryDirectory.appendingPathComponent("nfsmw-existing-\(UUID().uuidString)")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDown() {
        try? fm.removeItem(at: root)
    }

    @discardableResult
    private func makeApp(in directory: URL, bundleID: String = gameBundleID, stamp: String? = nil,
                         game: String = "old game") throws -> URL {
        let app = directory.appendingPathComponent("NFSMW.app")
        let resources = app.appendingPathComponent("Contents/Resources/game")
        try fm.createDirectory(at: resources, withIntermediateDirectories: true)
        var info: [String: Any] = ["CFBundleIdentifier": bundleID]
        if let stamp = stamp { info[builderVersionKey] = stamp }
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0)
            .write(to: app.appendingPathComponent("Contents/Info.plist"))
        try game.write(to: resources.appendingPathComponent("speed.exe"), atomically: true, encoding: .utf8)
        return app
    }

    private func directory(_ name: String) throws -> URL {
        let url = root.appendingPathComponent(name)
        try fm.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    func testFindsAppInDestinationThenApplications() throws {
        let destination = try directory("Games"), applications = try directory("Applications")
        XCTAssertNil(findExistingApp(destination: destination, fallback: applications))
        let fallback = try makeApp(in: applications)
        XCTAssertEqual(findExistingApp(destination: destination, fallback: applications)?.path, fallback.path)
        let saved = try makeApp(in: destination)
        XCTAssertEqual(findExistingApp(destination: destination, fallback: applications)?.path, saved.path)
    }

    func testIgnoresUnrelatedAndLinkedApps() throws {
        let destination = try directory("Games"), applications = try directory("Applications")
        let real = try makeApp(in: try directory("Elsewhere"))
        try fm.createSymbolicLink(at: destination.appendingPathComponent("NFSMW.app"), withDestinationURL: real)
        try makeApp(in: applications, bundleID: "com.example.other")
        XCTAssertNil(findExistingApp(destination: destination, fallback: applications))
        XCTAssertFalse(isGameApp(destination.appendingPathComponent("NFSMW.app")))
        XCTAssertTrue(isGameApp(real))
    }

    func testReadsTheBuilderVersionStamp() throws {
        XCTAssertEqual(builderVersion(of: try makeApp(in: try directory("a"), stamp: "0.3.6")), "0.3.6")
        XCTAssertNil(builderVersion(of: try makeApp(in: try directory("b"))))
        XCTAssertNil(builderVersion(of: root.appendingPathComponent("missing.app")))
    }

    func testBuildButtonTitle() {
        XCTAssertEqual(buildButtonTitle(updating: true, oldVersion: "0.3.6", newVersion: "0.4.0"),
                       "Update NFSMW.app (0.3.6 -> 0.4.0)")
        XCTAssertEqual(buildButtonTitle(updating: true, oldVersion: nil, newVersion: "0.4.0"), "Update NFSMW.app")
        XCTAssertEqual(buildButtonTitle(updating: false, oldVersion: "0.3.6", newVersion: "0.4.0"), "Build NFSMW.app")
    }

    /// The old app stays complete and unchanged until a complete new one replaces it in one step.
    func testUpdateKeepsOldAppUntilTheNewOneIsComplete() throws {
        let destination = try directory("Applications")
        let old = try makeApp(in: destination, stamp: "0.3.6")
        let oldGame = old.appendingPathComponent("Contents/Resources/game/speed.exe")
        let incomplete = try directory("build/incomplete.app")
        XCTAssertThrowsError(try installApp(incomplete, into: destination, isRunning: { false }))
        XCTAssertEqual(try String(contentsOf: oldGame, encoding: .utf8), "old game")
        XCTAssertEqual(builderVersion(of: old), "0.3.6")
        XCTAssertThrowsError(try installApp(try makeApp(in: try directory("build/next"), stamp: "0.4.0"),
                                            into: destination, isRunning: { true }))
        XCTAssertEqual(try String(contentsOf: oldGame, encoding: .utf8), "old game")
        let built = try makeApp(in: try directory("build/final"), stamp: "0.4.0", game: "new game")
        let installed = try installApp(built, into: destination, isRunning: { false })
        XCTAssertEqual(builderVersion(of: installed), "0.4.0")
        XCTAssertEqual(try String(contentsOf: installed.appendingPathComponent("Contents/Resources/game/speed.exe"),
                                  encoding: .utf8), "new game")
        XCTAssertFalse(fm.fileExists(atPath: destination.appendingPathComponent(".NFSMW.app.installing").path))
    }
}
