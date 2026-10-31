import XCTest
@testable import BuilderCore

final class PipelineRunnerTests: XCTestCase {
    private var tmp: URL!
    private let fm = FileManager.default

    override func setUpWithError() throws {
        tmp = fm.temporaryDirectory.appendingPathComponent("nfsmw runner \"q\" ö-\(UUID().uuidString)")
        try fm.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? fm.removeItem(at: tmp)
    }

    // MARK: - Helpers

    private func runner(_ executable: String, _ arguments: [String],
                        environment: [String: String] = ["PATH": "/usr/bin:/bin"]) -> PipelineRunner {
        PipelineRunner(executable: URL(fileURLWithPath: executable), arguments: arguments,
                       workingDirectory: tmp, environment: environment)
    }

    /// `/bin/sh -c script sh args...`: the script sees `args` as $1, $2, ...
    private func shell(_ script: String, _ args: [String] = []) -> PipelineRunner {
        runner("/bin/sh", ["-c", script, "sh"] + args)
    }

    private final class Recording {
        var events: [PipelineEvent] = []
        var status: Int32?
        var eventsAtExit: Int?
        var offMain = false
        var eventsAfterExit = false
    }

    /// Starts the runner and waits for onExit; `onEvent` runs for every event before it is recorded.
    @discardableResult
    private func run(_ runner: PipelineRunner, timeout: TimeInterval = 20,
                     onEvent: ((PipelineEvent) -> Void)? = nil) throws -> Recording {
        let recording = Recording()
        let exited = expectation(description: "onExit")
        try runner.start(onEvent: { event in
            if !Thread.isMainThread { recording.offMain = true }
            if recording.status != nil { recording.eventsAfterExit = true }
            recording.events.append(event)
            onEvent?(event)
        }, onExit: { status in
            if !Thread.isMainThread { recording.offMain = true }
            recording.status = status
            recording.eventsAtExit = recording.events.count
            exited.fulfill()
        })
        wait(for: [exited], timeout: timeout)
        XCTAssertFalse(recording.offMain, "callbacks must run on the main queue")
        XCTAssertFalse(recording.eventsAfterExit, "onExit must come after all events")
        return recording
    }

    private func waitUntilGone(_ pid: pid_t, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if kill(pid, 0) == -1 && errno == ESRCH { return true }
            usleep(10_000)
        } while Date() < deadline
        return false
    }

    private func openDescriptorCount() -> Int {
        let limit = min(Int32(getdtablesize()), 65_536)
        return (0..<limit).filter { fcntl($0, F_GETFD) != -1 }.count
    }

    /// Runs `script` (which must write "$$" then the background pid to $1 and then print "ready"),
    /// cancels once "ready" arrives, and returns the exit status, the pids and the cancel-to-exit time.
    private func cancelAfterReady(_ script: String, grace: TimeInterval? = nil,
                                  timeout: TimeInterval) throws -> (status: Int32?, pids: [pid_t], elapsed: TimeInterval) {
        let pidfile = tmp.appendingPathComponent("pids")
        let r = shell(script, [pidfile.path])
        if let grace = grace { r.killGracePeriod = grace }
        let ready = expectation(description: "ready")
        let exited = expectation(description: "onExit")
        var status: Int32?
        try r.start(onEvent: { if $0 == .log("ready") { ready.fulfill() } },
                    onExit: { status = $0; exited.fulfill() })
        wait(for: [ready], timeout: 10)
        let pids = (try String(contentsOf: pidfile, encoding: .utf8))
            .split(separator: "\n").compactMap { pid_t(String($0)) }
        XCTAssertEqual(pids.count, 2)
        let cancelled = Date()
        r.cancel()
        wait(for: [exited], timeout: timeout)
        return (status, pids, Date().timeIntervalSince(cancelled))
    }

    // MARK: - Spec tests

    func testArgumentsWithSpacesQuotesAndUnicodeArriveIntact() throws {
        let argument = #"~/Games/NFS Most Wanted "copy"/Disc 1 (USA) ö.iso"#
        let r = try run(runner("/bin/echo", [argument]))
        XCTAssertEqual(r.events, [.log(argument)])
        XCTAssertEqual(r.status, 0)
    }

    func testEventsAndExitStatus() throws {
        let r = try run(shell(#"echo 'NFSMW-EVENT {"step":"check","title":"Checking"}'; echo hello >&2; exit 3"#))
        XCTAssertEqual(r.events, [.step(id: "check", title: "Checking"), .log("hello")])
        XCTAssertEqual(r.status, 3)
    }

    func testCancelStopsWholeProcessGroup() throws {
        let result = try cancelAfterReady(#"echo $$ > "$1"; sleep 60 & echo $! >> "$1"; echo ready; wait"#,
                                          timeout: 6)
        XCTAssertEqual(result.status, 128 + SIGTERM)
        XCTAssertLessThan(result.elapsed, 6)
        for pid in result.pids {
            XCTAssertTrue(waitUntilGone(pid, timeout: 6 - min(result.elapsed, 5)), "pid \(pid) still alive")
        }
    }

    // MARK: - Process control

    func testCancelEscalatesToKillWhenTermIsIgnored() throws {
        let result = try cancelAfterReady(#"trap '' TERM; echo $$ > "$1"; sleep 60 & echo $! >> "$1"; echo ready; wait"#,
                                          grace: 0.3, timeout: 10)
        XCTAssertEqual(result.status, 128 + SIGKILL)
        XCTAssertGreaterThanOrEqual(result.elapsed, 0.3)
        for pid in result.pids {
            XCTAssertTrue(waitUntilGone(pid, timeout: 5), "pid \(pid) still alive")
        }
    }

    func testLeftoverBackgroundProcessIsStoppedWhenChildExits() throws {
        let pidfile = tmp.appendingPathComponent("pid")
        let r = try run(shell(#"sleep 60 & echo $! > "$1"; echo bye; exit 4"#, [pidfile.path]), timeout: 10)
        XCTAssertEqual(r.events, [.log("bye")])
        XCTAssertEqual(r.status, 4)
        let pid = try XCTUnwrap(pid_t(try String(contentsOf: pidfile, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)))
        XCTAssertTrue(waitUntilGone(pid, timeout: 5), "background sleep outlived the pipeline")
    }

    func testDefaultKillGracePeriodIsFiveSeconds() {
        XCTAssertEqual(shell("true").killGracePeriod, 5)
    }

    func testCancelBeforeStartAndAfterExitIsHarmless() throws {
        let r = shell("echo once")
        r.cancel()
        let recording = try run(r)
        XCTAssertEqual(recording.events, [.log("once")])
        XCTAssertEqual(recording.status, 0)
        r.cancel()
        r.cancel()
    }

    func testStartingTwiceThrows() throws {
        let r = shell("true")
        try run(r)
        XCTAssertThrowsError(try r.start(onEvent: { _ in }, onExit: { _ in }))
    }

    func testMissingExecutableThrows() {
        let r = runner(tmp.appendingPathComponent("no such python").path, [])
        XCTAssertThrowsError(try r.start(onEvent: { _ in }, onExit: { _ in }))
    }

    func testMissingWorkingDirectoryThrows() {
        let r = PipelineRunner(executable: URL(fileURLWithPath: "/bin/echo"), arguments: [],
                               workingDirectory: tmp.appendingPathComponent("gone"), environment: [:])
        XCTAssertThrowsError(try r.start(onEvent: { _ in }, onExit: { _ in }))
    }

    // MARK: - Output

    func testTrailingPartialLineIsFlushed() throws {
        let r = try run(shell(#"printf 'one\ntwo'; printf 'err' >&2"#))
        XCTAssertEqual(r.events.count, 3)
        XCTAssertTrue(r.events.contains(.log("err")))
        XCTAssertEqual(r.events.filter { $0 != .log("err") }, [.log("one"), .log("two")])
    }

    func testCarriageReturnLineEndingsAreStripped() throws {
        let r = try run(shell(#"printf 'one\r\ntwo\r\n'"#))
        XCTAssertEqual(r.events, [.log("one"), .log("two")])
    }

    func testFullStderrPipeDoesNotDeadlock() throws {
        // 50000 stderr lines (about 200 KB, far past a pipe buffer) before anything on stdout.
        let r = try run(shell("yes err | head -n 50000 >&2; yes out | head -n 50000; echo end"))
        XCTAssertEqual(r.status, 0)
        XCTAssertEqual(r.events.count, 100_001)
        XCTAssertEqual(r.eventsAtExit, 100_001)
        XCTAssertEqual(r.events.filter { $0 == .log("err") }.count, 50_000)
        XCTAssertEqual(r.events.filter { $0 == .log("out") }.count, 50_000)
        XCTAssertEqual(r.events.last, .log("end"))
    }

    func testNonzeroExitWithoutErrorEventIsPassedThrough() throws {
        let r = try run(shell("echo working; exit 1"))
        XCTAssertEqual(r.events, [.log("working")])
        XCTAssertEqual(r.status, 1)
    }

    // MARK: - Child setup

    func testChildRunsInWorkingDirectoryWithExactEnvironment() throws {
        let env = ["PATH": "/usr/bin:/bin", "NFSMW_TEST": #"a b "c" ö"#]
        let pwd = try run(runner("/bin/pwd", ["-P"], environment: env))
        var resolved = [CChar](repeating: 0, count: Int(PATH_MAX))
        XCTAssertNotNil(realpath(tmp.path, &resolved))
        XCTAssertEqual(pwd.events, [.log(String(cString: resolved))])

        let printed = try run(runner("/usr/bin/env", [], environment: env))
        let lines = printed.events.compactMap { event -> String? in
            if case .log(let line) = event { return line }
            return nil
        }
        XCTAssertEqual(lines.sorted(), env.map { "\($0.key)=\($0.value)" }.sorted())
    }

    func testChildOwnsItsProcessGroup() throws {
        let r = try run(shell(#"echo "$$ $(ps -o pgid= -p $$)""#))
        guard case .log(let line)? = r.events.first else { return XCTFail("no output") }
        let fields = line.split(separator: " ").map(String.init)
        XCTAssertEqual(fields.count, 2)
        XCTAssertEqual(fields.first, fields.last, "child must lead its own process group")
        XCTAssertNotEqual(fields.last.flatMap { pid_t($0) }, getpgrp())
    }

    func testChildGetsOnlyStandardDescriptors() throws {
        let stray = open("/dev/null", O_RDONLY)
        XCTAssertGreaterThan(stray, 2)
        defer { close(stray) }
        let script = #"""
        if [ -e /dev/fd/$1 ]; then echo "fd $1 open"; else echo "fd $1 closed"; fi
        if [ "$(stat -L -f %r /dev/fd/0)" = "$(stat -f %r /dev/null)" ]; then echo "stdin null"; else echo "stdin other"; fi
        cat
        echo done
        """#
        let r = try run(shell(script, [String(stray)]))
        XCTAssertEqual(r.events, [.log("fd \(stray) closed"), .log("stdin null"), .log("done")])
    }

    func testNoDescriptorsLeakInTheParent() throws {
        let before = openDescriptorCount()
        for _ in 0..<5 {
            try run(shell("echo out; echo err >&2"))
        }
        try run(shell("yes x | head -n 20000"))
        _ = try? runner("/nonexistent/python", []).start(onEvent: { _ in }, onExit: { _ in })
        _ = try? cancelAfterReady(#"echo $$ > "$1"; sleep 60 & echo $! >> "$1"; echo ready; wait"#, timeout: 6)
        XCTAssertEqual(openDescriptorCount(), before)
    }

    // MARK: - Environment and constructors

    func testPipelineEnvironment() {
        let inherited = ["HOME": "/Users/someone", "PATH": "/opt/homebrew/bin:/usr/bin", "PYTHONPATH": "/x", "LANG": "C"]
        XCTAssertEqual(PipelineRunner.pipelineEnvironment(inherited),
                       ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONUNBUFFERED": "1", "HOME": "/Users/someone"])
        var withCache = inherited
        withCache["NFSMW_CACHE_DIR"] = "/Volumes/Cache Disk/NFSMW"
        XCTAssertEqual(PipelineRunner.pipelineEnvironment(withCache)["NFSMW_CACHE_DIR"], "/Volumes/Cache Disk/NFSMW")
        XCTAssertEqual(PipelineRunner.pipelineEnvironment([:])["HOME"], NSHomeDirectory())
        let paths = BuilderPaths(support: tmp, cache: tmp.appendingPathComponent("cache"))
        XCTAssertEqual(PipelineRunner.cacheDirectory(paths, withCache).path, "/Volumes/Cache Disk/NFSMW")
        XCTAssertEqual(PipelineRunner.cacheDirectory(paths, inherited), paths.cache)
    }

    func testConvenienceConstructors() throws {
        let paths = BuilderPaths(support: tmp, cache: tmp.appendingPathComponent("Caches/NFSMW/downloads"))
        let workspace = paths.workspace(version: "1.2.0")
        let venv = paths.venvPython(version: "1.2.0")
        let cache = PipelineRunner.cacheDirectory(paths).path
        let game = [URL(fileURLWithPath: #"/Users/x/Games/NFS Most Wanted "copy"/Disc 1 (USA).iso"#),
                    URL(fileURLWithPath: #"/Users/x/Games/NFS Most Wanted "copy"/Disc "2".iso"#)]
        let file = URL(fileURLWithPath: "/Users/x/Downloads/MW_HQ_1.20.9 (1).zip")
        let expected: [(PipelineRunner, URL, [String])] = [
            (.setup(paths: paths, version: "1.2.0"), paths.pythonExecutable, ["tools/build_app.py", "--setup-only"]),
            (.checkGame(paths: paths, version: "1.2.0", game: game), venv,
             ["tools/builder_cli.py", "check-game"] + game.map(\.path)),
            (.acceptedCopies(paths: paths, version: "1.2.0"), venv, ["tools/builder_cli.py", "accepted-copies"]),
            (.downloadsStatus(paths: paths, version: "1.2.0"), venv,
             ["tools/builder_cli.py", "downloads", "status", "--cache-dir", cache]),
            (.importDownload(paths: paths, version: "1.2.0", file: file), venv,
             ["tools/builder_cli.py", "downloads", "import", "mw-hq", file.path, "--cache-dir", cache]),
            (.build(paths: paths, version: "1.2.0", game: game), venv,
             ["tools/build_app.py", "--progress", "--cache-dir", cache, "--"] + game.map(\.path)),
        ]
        for (runner, executable, arguments) in expected {
            XCTAssertEqual(runner.executable, executable)
            XCTAssertEqual(runner.arguments, arguments)
            XCTAssertEqual(runner.workingDirectory, workspace)
            XCTAssertEqual(runner.environment, PipelineRunner.pipelineEnvironment())
        }
        let fetch = PipelineRunner.fetchDownloads(paths: paths, version: "1.2.0")
        XCTAssertEqual(fetch.arguments, ["tools/builder_cli.py", "downloads", "fetch", "--cache-dir", cache])
        XCTAssertEqual(fetch.environment["NFSMW_PROGRESS"], "1")
    }

    func testSeveralGamePathsArriveAsSeparateArguments() throws {
        let paths = BuilderPaths(support: tmp)
        let game = [URL(fileURLWithPath: "/tmp/a b/Disc 1 (USA).iso"), URL(fileURLWithPath: #"/tmp/a b/Disc "2".iso"#)]
        let runner = PipelineRunner.build(paths: paths, version: "1", game: game)
        XCTAssertEqual(Array(runner.arguments.suffix(2)), ["/tmp/a b/Disc 1 (USA).iso", #"/tmp/a b/Disc "2".iso"#])
        let echo = try run(self.runner("/bin/sh", ["-c", #"for a in "$@"; do echo "[$a]"; done"#, "sh"] + game.map(\.path)))
        XCTAssertEqual(echo.events, [.log("[/tmp/a b/Disc 1 (USA).iso]"), .log(#"[/tmp/a b/Disc "2".iso]"#)])
    }

    func testBuildPassesCacheAndHelpers() throws {
        let paths = BuilderPaths(support: tmp, cache: tmp.appendingPathComponent("cache"))
        let helpers = paths.helpers(version: "1")
        try fm.createDirectory(at: helpers, withIntermediateDirectories: true)
        try "{}".write(to: helpers.appendingPathComponent("helpers.json"), atomically: true, encoding: .utf8)
        let arguments = PipelineRunner.build(paths: paths, version: "1", game: [URL(fileURLWithPath: "/g")]).arguments
        let cache = PipelineRunner.cacheDirectory(paths).path
        XCTAssertEqual(arguments, ["tools/build_app.py", "--progress", "--cache-dir", cache, "--helpers", helpers.path, "--", "/g"])
        XCTAssertEqual(PipelineRunner.downloadsStatus(paths: paths, version: "1").arguments.suffix(3),
                       ["--cache-dir", cache, "--helpers"])
    }
}
