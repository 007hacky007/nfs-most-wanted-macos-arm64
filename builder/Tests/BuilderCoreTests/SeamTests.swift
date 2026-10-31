import XCTest
import BuilderCore

/// Parses real tools/builder_cli.py output (Fixtures/builder-events.txt, regenerated and
/// checked by tests/test_builder_events_fixture.py), so Python and Swift cannot drift apart.
final class SeamTests: XCTestCase {
    func testRealBuilderCliOutputParses() throws {
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/builder-events.txt")
        let lines = try String(contentsOf: fixture, encoding: .utf8).split(separator: "\n").map(String.init)
        XCTAssertEqual(lines.count, 3)
        let events = lines.map(parsePipelineLine)

        guard case let .accepted(copies) = events[0] else { return XCTFail("accepted-copies: \(events[0])") }
        XCTAssertEqual(copies.folder.requiredFiles, 1407)
        XCTAssertEqual(copies.discsTotal, 2_245_282_662)
        XCTAssertEqual(copies.discs.map(\.disc), [1, 2, 3, 4])
        XCTAssertEqual(copies.folder.executables.count, 2)

        guard case let .downloads(status) = events[1] else { return XCTFail("downloads status: \(events[1])") }
        XCTAssertEqual(status.downloads["mw-hq"], "partial")
        XCTAssertEqual(status.partialBytes["mw-hq"], 5)
        XCTAssertGreaterThanOrEqual(status.remainingBytes, 0)
        XCTAssertEqual(status.cachedBytes, 5)

        guard case let .gameRejected(message, report) = events[2] else { return XCTFail("check-game: \(events[2])") }
        XCTAssertTrue(message.hasPrefix("This is not the supported game copy."))
        XCTAssertEqual(report.kind, "folder")
        XCTAssertEqual(report.failed, 1407)
        XCTAssertEqual(report.problems.count, 20)
        XCTAssertTrue(report.problems.allSatisfy { !$0.path.isEmpty && !$0.accepted.isEmpty })
        XCTAssertTrue(report.problems.contains { $0.found == .missing })
        XCTAssertFalse(report.ok)
    }
}
