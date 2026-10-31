import XCTest
import BuilderCore

/// Drives the same BuilderCore calls as the Builder window against a real game copy.
///
/// Skipped unless NFSMW_E2E_GAME names a game folder or a folder of the four disc images and
/// NFSMW_E2E_HELPERS names a tools/build_helpers.py output folder. Downloads the private Python
/// and the packages, so it needs the network. NFSMW_E2E_DOWNLOADS may name a folder holding the
/// pinned downloads; they are cloned (cp -c) into a temporary cache, never used in place.
/// NFSMW_E2E_SOURCES may name an assembled app's Contents/Resources/BuildSources.
///
/// The pipeline only ever sees temporary clones: the game copy and the downloads folder are
/// snapshotted (paths, sizes, modification times) and must be unchanged at the end.
/// Needs about 40 GB free. Prints measurements with the E2E prefix.
final class EndToEndTests: XCTestCase {
    private let fm = FileManager.default
    private let version = "0.0.0-e2e"
    private static let pinnedDownloads = ["nfsmwpatch1.3.exe", "NFSMostWanted.WidescreenFix.zip", "MW_HQ_1.20.9.zip",
                                          "innoextract-source.tar.gz"]

    func testFullBuildFromWindowCalls() throws {
        let env = ProcessInfo.processInfo.environment
        guard let gamePath = env["NFSMW_E2E_GAME"], let helperPath = env["NFSMW_E2E_HELPERS"] else {
            throw XCTSkip("set NFSMW_E2E_GAME and NFSMW_E2E_HELPERS to run the end-to-end build")
        }
        unsetenv("NFSMW_CACHE_DIR")
        let tmp = fm.temporaryDirectory.appendingPathComponent("nfsmw-e2e-\(UUID().uuidString)")
        try fm.createDirectory(at: tmp, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: tmp) }
        let started = Date()
        func mark(_ what: String) { print("E2E \(String(format: "%7.1f", Date().timeIntervalSince(started))) s: \(what)") }

        // Clone the inputs; the originals are only read by cp.
        let original = URL(fileURLWithPath: gamePath)
        let originalSnapshot = try snapshot(original)
        let game = tmp.appendingPathComponent("game")
        try clone(original, to: game)
        let cache = tmp.appendingPathComponent("cache")
        try fm.createDirectory(at: cache, withIntermediateDirectories: true)
        var downloadsSnapshot: [String]?
        if let folder = env["NFSMW_E2E_DOWNLOADS"].map({ URL(fileURLWithPath: $0) }) {
            downloadsSnapshot = try snapshot(folder)
            for name in Self.pinnedDownloads where fm.fileExists(atPath: folder.appendingPathComponent(name).path) {
                try clone(folder.appendingPathComponent(name), to: cache.appendingPathComponent(name))
            }
        }
        let paths = BuilderPaths(support: tmp.appendingPathComponent("support"), cache: cache)
        XCTAssertEqual(PipelineRunner.cacheDirectory(paths), cache)
        let sampler = Sampler(volume: tmp)
        sampler.start()
        mark("inputs cloned")

        let sources = try env["NFSMW_E2E_SOURCES"].map { URL(fileURLWithPath: $0) } ?? repositoryRoot()
        try prepareWorkspace(sources: sources, destination: paths.workspace(version: version), version: version)
        if !fm.fileExists(atPath: paths.helpers(version: version).path) {
            try fm.copyItem(at: URL(fileURLWithPath: helperPath), to: paths.helpers(version: version))
        }
        mark("workspace prepared")

        let installed = expectation(description: "python")
        var installResult: Result<Void, Error>?
        PythonRuntime.install(paths, download: { url, done in
            URLSession.shared.downloadTask(with: url) { file, response, error in
                if let file = file, (response as? HTTPURLResponse)?.statusCode == 200 {
                    done(.success(file))
                } else {
                    done(.failure(error ?? URLError(.badServerResponse)))
                }
            }.resume()
        }, completion: { result in
            installResult = result
            installed.fulfill()
        })
        wait(for: [installed], timeout: 600)
        try XCTUnwrap(installResult).get()
        mark("python installed")

        let setup = try run(.setup(paths: paths, version: version), timeout: 900)
        XCTAssertEqual(setup.status, 0, setup.lines.suffix(30).joined(separator: "\n"))
        XCTAssertEqual(buildToolsCheck(paths: paths, version: version, requireHelpers: true), .ready("Installed"))
        mark("setup done")

        let accepted = try run(.acceptedCopies(paths: paths, version: version), timeout: 120)
        XCTAssertTrue(accepted.events.contains { if case let .accepted(copies) = $0 { return copies.folder.requiredFiles == 1407 }; return false })

        let check = try run(.checkGame(paths: paths, version: version, game: [game]), timeout: 900)
        XCTAssertEqual(check.status, 0, check.lines.suffix(30).joined(separator: "\n"))
        let detected = check.events.compactMap { event -> String? in
            if case let .game(version, _) = event { return version }
            return nil
        }
        XCTAssertEqual(detected.count, 1)
        mark("game checked: \(detected.first ?? "none")")

        // A second clone with one truncated file: the report names exactly that file.
        let broken = tmp.appendingPathComponent("broken")
        try clone(game, to: broken)
        let victim = try largestFile(in: broken)
        let handle = try FileHandle(forWritingTo: victim)
        try handle.truncate(atOffset: 4096)
        try handle.close()
        let rejected = try run(.checkGame(paths: paths, version: version, game: [broken]), timeout: 900)
        XCTAssertEqual(rejected.status, 1)
        let rejection = rejected.events.compactMap { event -> (String, GameReport)? in
            if case let .gameRejected(message, report) = event { return (message, report) }
            return nil
        }.first
        let named = rejection.map { $0.0.contains(victim.lastPathComponent)
            || $0.1.problems.map(\.path) == [victim.path.replacingOccurrences(of: broken.path + "/", with: "")] }
        XCTAssertEqual(named, true, "\(String(describing: rejection))")
        try fm.removeItem(at: broken)
        mark("truncated \(victim.lastPathComponent) rejected: \(rejection?.0 ?? "no event")")

        let status = try run(.downloadsStatus(paths: paths, version: version), timeout: 120)
        let decoded = status.events.compactMap { event -> DownloadsStatus? in
            if case let .downloads(s) = event { return s }
            return nil
        }
        XCTAssertEqual(decoded.count, 1, "downloads status did not decode: \(status.lines)")
        XCTAssertGreaterThanOrEqual(decoded.first?.remainingBytes ?? -1, 0)
        mark("downloads status: \(decoded.first.map { "\($0.downloads)" } ?? "none")")

        // First build: cancel while the game is being translated; nothing from it may survive.
        let workspace = paths.workspace(version: version).path
        var group: pid_t = 0
        let cancelled = try run(.build(paths: paths, version: version, game: [game]), timeout: 7200) { event, runner in
            guard case .step(id: "translate", _) = event else { return }
            group = Self.processGroup(matching: { $0.contains(workspace) && $0.contains("build_app.py") }) ?? 0
            let deadline = Date().addingTimeInterval(60)
            while Date() < deadline && Self.processes(inGroup: group).count < 3 { usleep(500_000) }
            mark("translate started (group \(group), \(Self.processes(inGroup: group).count) processes), cancelling")
            runner.cancel()
        }
        XCTAssertNotEqual(group, 0, "found the build's process group")
        XCTAssertNotEqual(cancelled.status, 0)
        let deadline = Date().addingTimeInterval(6)
        var leftovers: [String] = []
        repeat {
            leftovers = Self.processes(inGroup: group)
                + ["clang", "build_app", "nfsmw_boot", "innoextract", "gen.sh"].flatMap { pattern in
                    Self.pgrep(pattern).compactMap { pid in Self.processGroup(of: pid) == group ? "\(pattern) \(pid)" : nil }
                }
            if leftovers.isEmpty { break }
            usleep(100_000)
        } while Date() < deadline
        XCTAssertEqual(leftovers, [], "processes from the cancelled build survived")
        mark("cancelled build exited with \(cancelled.status); nothing left running")

        // Second build runs to the end.
        var stepTimes: [(String, Date)] = []
        var buildGroup: pid_t = 0
        let full = try run(.build(paths: paths, version: version, game: [game]), timeout: 10800) { event, _ in
            if case let .step(id, title) = event {
                stepTimes.append((id, Date()))
                mark("step \(id): \(title)")
                if buildGroup == 0 {
                    buildGroup = Self.processGroup(matching: { $0.contains(workspace) && $0.contains("build_app.py") }) ?? 0
                    sampler.group = buildGroup
                }
            }
        }
        stepTimes.append(("end", Date()))
        XCTAssertEqual(full.status, 0, full.lines.suffix(60).joined(separator: "\n"))
        let built = try XCTUnwrap(full.events.compactMap { event -> URL? in
            if case let .done(url) = event { return url }
            return nil
        }.first)
        for (index, (id, date)) in stepTimes.dropLast().enumerated() {
            print("E2E step \(id): \(String(format: "%.0f", stepTimes[index + 1].1.timeIntervalSince(date))) s")
        }
        let appSize = allocatedSize(of: built)
        print("E2E peak disk used: \(gigabytes(sampler.peakUsed)), peak group memory: \(gigabytes(sampler.peakResident)), app: \(gigabytes(appSize))")

        let destination = tmp.appendingPathComponent("Applications")
        try fm.createDirectory(at: destination, withIntermediateDirectories: true)
        let app = try installApp(built, into: destination, isRunning: { false })
        XCTAssertEqual(app.lastPathComponent, "NFSMW.app")
        let verify = SystemCommandRunner().run("/usr/bin/codesign", ["--verify", "--deep", "--strict", app.path])
        XCTAssertEqual(verify.status, 0, verify.output)
        let quarantine = SystemCommandRunner().run("/usr/bin/xattr", ["-r", app.path]).output
        XCTAssertFalse(quarantine.contains("com.apple.quarantine"))
        let freed = removeBuildFiles(paths, version: version)
        mark("installed, codesign verified, build files removed (\(gigabytes(freed)))")
        sampler.stop()

        XCTAssertEqual(try snapshot(original), originalSnapshot, "the game copy changed")
        if let folder = env["NFSMW_E2E_DOWNLOADS"], let before = downloadsSnapshot {
            XCTAssertEqual(try snapshot(URL(fileURLWithPath: folder)), before, "the downloads folder changed")
        }
    }

    // MARK: - Helpers

    /// Samples free space on the volume and the resident memory of the build's process group.
    private final class Sampler {
        let volume: URL
        var group: pid_t = 0
        private(set) var peakUsed: Int64 = 0
        private(set) var peakResident: Int64 = 0
        private var timer: DispatchSourceTimer?
        private var startFree: Int64 = 0

        init(volume: URL) { self.volume = volume }

        private var ticks = 0

        /// statfs, not URL resource values: those are cached per URL and never change.
        private func free() -> Int64 {
            var info = statfs()
            guard statfs(volume.path, &info) == 0 else { return startFree }
            return Int64(info.f_bavail) * Int64(info.f_bsize)
        }

        func start() {
            startFree = free()
            let timer = DispatchSource.makeTimerSource(queue: .global())
            timer.schedule(deadline: .now(), repeating: 2)
            timer.setEventHandler { [self] in
                peakUsed = max(peakUsed, startFree - free())
                ticks += 1
                guard group != 0, ticks % 5 == 0 else { return }
                let output = SystemCommandRunner().run("/bin/ps", ["-g", "\(group)", "-o", "rss="]).output
                let resident = output.split(separator: "\n").compactMap { Int64($0.trimmingCharacters(in: .whitespaces)) }
                    .reduce(0, +) * 1024
                peakResident = max(peakResident, resident)
            }
            timer.resume()
            self.timer = timer
        }

        func stop() { timer?.cancel() }
    }

    private func clone(_ source: URL, to target: URL) throws {
        let result = SystemCommandRunner().run("/bin/cp", ["-c", "-R", source.path, target.path])
        guard result.status == 0 else { throw XCTSkip("could not clone \(source.lastPathComponent): \(result.output)") }
    }

    private func snapshot(_ root: URL) throws -> [String] {
        guard let walker = fm.enumerator(at: root, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey])
        else { return [] }
        return walker.compactMap { item -> String? in
            guard let url = item as? URL,
                  let values = try? url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey]) else { return nil }
            return "\(url.path.replacingOccurrences(of: root.path, with: "")) \(values.fileSize ?? -1) "
                + "\(values.contentModificationDate?.timeIntervalSince1970 ?? 0)"
        }.sorted()
    }

    private func largestFile(in root: URL) throws -> URL {
        let files = (fm.enumerator(at: root, includingPropertiesForKeys: [.fileSizeKey])?.allObjects as? [URL]) ?? []
        func size(_ url: URL) -> Int { (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0 }
        return try XCTUnwrap(files.max { size($0) < size($1) })
    }

    private struct Run {
        var events: [PipelineEvent] = []
        var lines: [String] = []
        var status: Int32 = -1
    }

    private func run(_ runner: PipelineRunner, timeout: TimeInterval,
                     onEvent: ((PipelineEvent, PipelineRunner) -> Void)? = nil) throws -> Run {
        var result = Run()
        let exited = expectation(description: "exit")
        try runner.start(onEvent: { event in
            result.events.append(event)
            switch event {
            case let .log(line): result.lines.append(line)
            case let .step(_, title): result.lines.append(title)
            case let .error(message, _): result.lines.append("Error: \(message)")
            case let .gameRejected(message, _): result.lines.append("Rejected: \(message)")
            default: break
            }
            onEvent?(event, runner)
        }, onExit: { status in
            result.status = status
            exited.fulfill()
        })
        wait(for: [exited], timeout: timeout)
        return result
    }

    private func repositoryRoot() throws -> URL {
        var url = URL(fileURLWithPath: #filePath)
        while url.path != "/" {
            url.deleteLastPathComponent()
            if fm.fileExists(atPath: url.appendingPathComponent("build.sh").path) { return url }
        }
        throw XCTSkip("repository root not found")
    }

    private static func ps() -> [(pid: pid_t, pgid: pid_t, command: String)] {
        let output = SystemCommandRunner().run("/bin/ps", ["-axww", "-o", "pid=,pgid=,command="]).output
        return output.split(separator: "\n").compactMap { line in
            let parts = line.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true)
            guard parts.count == 3, let pid = pid_t(parts[0]), let pgid = pid_t(parts[1]) else { return nil }
            return (pid, pgid, String(parts[2]))
        }
    }

    private static func processGroup(matching predicate: (String) -> Bool) -> pid_t? {
        ps().first { predicate($0.command) }?.pgid
    }

    private static func processGroup(of pid: pid_t) -> pid_t? {
        ps().first { $0.pid == pid }?.pgid
    }

    private static func processes(inGroup group: pid_t) -> [String] {
        ps().filter { $0.pgid == group }.map(\.command)
    }

    private static func pgrep(_ pattern: String) -> Set<pid_t> {
        let output = SystemCommandRunner().run("/usr/bin/pgrep", ["-f", pattern]).output
        return Set(output.split(separator: "\n").compactMap { pid_t($0.trimmingCharacters(in: .whitespaces)) })
    }
}
