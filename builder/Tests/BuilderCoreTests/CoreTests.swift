import XCTest
import BuilderCore

final class CoreTests: XCTestCase {
    static let report = #"{"ok": false, "kind": "folder", "version": null, "checked": 1407, "failed": 2, "problems": [{"path": "speed.exe", "found": {"size": 3, "sha256": "abc"}, "accepted": [{"kind": "source", "size": 7250800, "sha256": "2cf8"}]}, {"path": "GLOBAL/GlobalB.lzc", "found": "missing", "accepted": [{"kind": "source", "size": 10, "sha256": "ef01"}]}], "discs": null, "invalid": [], "wrong": [], "message": "This is not the supported game copy."}"#
    static let accepted = #"{"release": "Need for Speed Most Wanted (2005)", "not_supported": ["other regions"], "discs": [{"disc": 1, "archive": "0compressed.zip", "size": 612595273, "sha256": "d3a3"}], "discs_total": 2245282662, "folder": {"required_files": 1407, "total_original": 3028017159, "total_official": 3028022871, "executables": [{"kind": "source", "label": "Original disc executable", "size": 7250800, "sha256": "2cf8"}]}}"#

    func testBuildBlockedWhileAnyRowRedOrChecking() {
        var s = Dictionary(uniqueKeysWithValues: CheckID.allCases.map { ($0, CheckState.ready("ok")) })
        XCTAssertTrue(canBuild(s))
        s[.downloads] = .automatic("3.36 GB, downloaded during the build"); XCTAssertTrue(canBuild(s))
        s[.gameCopy] = .checking("checking"); XCTAssertFalse(canBuild(s))
        s[.gameCopy] = .blocked("choose"); XCTAssertFalse(canBuild(s))
        s.removeValue(forKey: .diskSpace); s[.gameCopy] = .ready("ok"); XCTAssertFalse(canBuild(s))
    }

    func testMacCheck() {
        XCTAssertTrue(macCheck(isAppleSilicon: true, version: .init(majorVersion: 12, minorVersion: 0, patchVersion: 0)).isReady)
        XCTAssertEqual(macCheck(isAppleSilicon: false, version: .init(majorVersion: 15, minorVersion: 0, patchVersion: 0)),
                       .blocked("NFSMW Builder needs a Mac with Apple Silicon"))
        XCTAssertEqual(macCheck(isAppleSilicon: true, version: .init(majorVersion: 11, minorVersion: 7, patchVersion: 0)),
                       .blocked("NFSMW Builder needs macOS 12 or newer. On macOS 11, build from Terminal."))
    }

    func testParseEvents() {
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"step":"translate","title":"Translating the game to C"}"#),
                       .step(id: "translate", title: "Translating the game to C"))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"done":"/tmp/w/out/NFSMW.app"}"#), .done(URL(fileURLWithPath: "/tmp/w/out/NFSMW.app")))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"error":"bad","log":"/tmp/a.log"}"#), .error(message: "bad", log: "/tmp/a.log"))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"error":"bad"}"#), .error(message: "bad", log: nil))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"error":"bad","log":null}"#), .error(message: "bad", log: nil))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"game":"ok","version":"USA","kind":"discs"}"#), .game(version: "USA", kind: "discs"))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"download":"mw-hq","received":10,"total":20}"#),
                       .download(key: "mw-hq", received: 10, total: 20))
        XCTAssertEqual(parsePipelineLine(#"NFSMW-EVENT {"downloads":"ready"}"#), .downloadsReady)
    }

    func testUnknownAndMalformedEventsAreLogText() {
        for line in [#"NFSV-EVENT {"done":"/x"}"#, "NFSMW-EVENT {broken", #"NFSMW-EVENT {"what":1}"#,
                     #"NFSMW-EVENT {"step":"x"}"#, #"NFSMW-EVENT ["step"]"#, #"NFSMW-EVENT {"download":"k","received":true,"total":2}"#,
                     #"NFSMW-EVENT {"error":"x","report":{"ok":false}}"#, #"NFSMW-EVENT {"downloads":"maybe"}"#, "plain"] {
            XCTAssertEqual(parsePipelineLine(line), .log(line), line)
        }
    }

    func testParseGameReport() throws {
        guard case let .gameRejected(message, report) = parsePipelineLine(#"NFSMW-EVENT {"error":"Not it.","report":"# + Self.report + "}")
        else { return XCTFail() }
        XCTAssertEqual(message, "Not it.")
        XCTAssertFalse(report.ok)
        XCTAssertEqual(report.kind, "folder")
        XCTAssertEqual([report.checked, report.failed], [1407, 2])
        XCTAssertEqual(report.problems[0].found, .file(FileDigest(size: 3, sha256: "abc")))
        XCTAssertEqual(report.problems[1].found, .missing)
        XCTAssertEqual(report.problems[1].accepted, [AcceptedFileFixture.make(kind: "source", size: 10, sha256: "ef01")])
        XCTAssertTrue(report.plainText.contains("- speed.exe: found 3 bytes, SHA-256 abc; accepted: 7250800 bytes, SHA-256 2cf8 (source)"))
        XCTAssertTrue(report.plainText.contains("- GLOBAL/GlobalB.lzc: missing"))
    }

    func testParseAcceptedCopiesAndDownloads() {
        guard case let .accepted(copies) = parsePipelineLine(#"NFSMW-EVENT {"accepted":"# + Self.accepted + "}") else { return XCTFail() }
        XCTAssertEqual(copies.folder.requiredFiles, 1407)
        XCTAssertEqual(copies.discsTotal, 2_245_282_662)
        XCTAssertEqual(copies.notSupported, ["other regions"])
        XCTAssertTrue(copies.plainText.contains("- Disc 1, 0compressed.zip: 612,595,273 bytes, SHA-256 d3a3"))
        XCTAssertTrue(copies.plainText.contains("1,407 required files, 3,028,017,159 bytes"))
        let line = #"NFSMW-EVENT {"downloads": {"official-1.3": "ready", "mw-hq": "partial"}, "partial_bytes": {"mw-hq": 5}, "total_bytes": 100, "remaining_bytes": 40}"#
        guard case let .downloads(status) = parsePipelineLine(line) else { return XCTFail() }
        XCTAssertEqual(status.downloads, ["official-1.3": "ready", "mw-hq": "partial"])
        XCTAssertEqual([status.partialBytes["mw-hq"], status.totalBytes, status.cachedBytes], [5, 100, 60])
        XCTAssertFalse(status.isReady)
    }

    func testProgress() {
        XCTAssertEqual(progressFraction(atStart: "check"), 0)
        XCTAssertEqual(progressFraction(atStart: "translate")!, 0.39, accuracy: 0.001)
        XCTAssertEqual(progressFraction(atStart: "package")!, 0.95, accuracy: 0.001)
        XCTAssertNil(progressFraction(atStart: "unknown"))
        XCTAssertEqual(progressFraction(step: "downloads", within: 0.5)!, 0.085, accuracy: 0.001)
        XCTAssertEqual(progressFraction(step: "downloads", within: 7)!, 0.16, accuracy: 0.001)
        XCTAssertNil(progressFraction(step: "setup", within: 0.5))
        XCTAssertEqual(buildSteps.reduce(0) { $0 + $1.weight }, 100)
        XCTAssertEqual(Set(buildStepNames.keys), Set(buildSteps.map(\.id)))
    }

    func testDiskSpaceNamesTheShortVolume() {
        let gb: Int64 = 1_000_000_000
        XCTAssertEqual(diskSpaceCheck(workspaceAvailable: 31_200_000_000, workspaceVolume: "Macintosh HD",
                                      destinationAvailable: 500 * gb, destinationVolume: "Games",
                                      sameVolume: false, cachedBytes: 0),
                       .blocked("Only 31.2 GB free on Macintosh HD, 45.0 GB needed during the build"))
        XCTAssertTrue(diskSpaceCheck(workspaceAvailable: 42 * gb, workspaceVolume: "Macintosh HD",
                                     destinationAvailable: 42 * gb, destinationVolume: "Macintosh HD",
                                     sameVolume: true, cachedBytes: 3_400_000_000).isReady)
        XCTAssertEqual(diskSpaceCheck(workspaceAvailable: 100 * gb, workspaceVolume: "Macintosh HD",
                                      destinationAvailable: 10 * gb, destinationVolume: "Games",
                                      sameVolume: false, cachedBytes: 0),
                       .blocked("Only 10.0 GB free on Games, 18.0 GB needed for NFSMW.app"))
        XCTAssertTrue(diskSpaceCheck(workspaceAvailable: 100 * gb, workspaceVolume: "Macintosh HD",
                                     destinationAvailable: 10 * gb, destinationVolume: "Macintosh HD",
                                     sameVolume: true, cachedBytes: 0).isReady)
    }
}

enum AcceptedFileFixture {
    static func make(kind: String, size: Int64, sha256: String) -> AcceptedFile {
        let json = #"{"kind": "\#(kind)", "size": \#(size), "sha256": "\#(sha256)"}"#
        return try! JSONDecoder().decode(AcceptedFile.self, from: Data(json.utf8))
    }
}
