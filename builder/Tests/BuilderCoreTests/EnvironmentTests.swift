import XCTest
@testable import BuilderCore

final class RecordingRunner: CommandRunning {
    var calls: [String] = []
    let results: [String: (status: Int32, output: String)]
    init(results: [String: (status: Int32, output: String)]) { self.results = results }
    func run(_ executable: String, _ arguments: [String]) -> (status: Int32, output: String) {
        calls.append(([executable] + arguments).joined(separator: " "))
        return results[executable] ?? (127, "")
    }
}

final class EnvironmentTests: XCTestCase {
    private var tmp: URL!
    private let fm = FileManager.default

    override func setUpWithError() throws {
        tmp = fm.temporaryDirectory.appendingPathComponent("nfsmw-env-\(UUID().uuidString)")
        try fm.createDirectory(at: tmp, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? fm.removeItem(at: tmp)
    }

    private func write(_ text: String, to url: URL) throws {
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: url, atomically: true, encoding: .utf8)
    }

    private func read(_ url: URL) -> String? { try? String(contentsOf: url, encoding: .utf8) }

    func testCLTDetectionNeverInvokesShims() {
        let runner = RecordingRunner(results: ["/usr/bin/xcode-select": (0, "/Library/Developer/CommandLineTools\n")])
        let clt = CommandLineTools(runner: runner, fileExists: {
            ["/Library/Developer/CommandLineTools/usr/bin/clang", "/usr/bin/codesign"].contains($0)
        })
        XCTAssertTrue(clt.state().isReady)
        XCTAssertFalse(runner.calls.contains { $0.contains("xcrun") || $0 == "/usr/bin/clang" })
        let missing = CommandLineTools(runner: RecordingRunner(results: ["/usr/bin/xcode-select": (2, "")]), fileExists: { _ in false })
        XCTAssertEqual(missing.state(), .blocked("Needed to compile the game on your Mac, about 2 GB from Apple"))
    }

    func testCLTAcceptsXcodeToolchainAndNeedsCodesign() {
        let runner = RecordingRunner(results: ["/usr/bin/xcode-select": (0, "/Applications/Xcode.app/Contents/Developer\n")])
        let clang = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
        XCTAssertTrue(CommandLineTools(runner: runner, fileExists: { [clang, "/usr/bin/codesign"].contains($0) }).state().isReady)
        if case .blocked = CommandLineTools(runner: runner, fileExists: { $0 == clang }).state() {} else { XCTFail("codesign missing") }
    }

    func testStartInstallRunsXcodeSelect() {
        let runner = RecordingRunner(results: [:])
        CommandLineTools(runner: runner, fileExists: { _ in false }).startInstall()
        XCTAssertEqual(runner.calls, ["/usr/bin/xcode-select --install"])
    }

    func testBuilderPaths() {
        let paths = BuilderPaths(support: URL(fileURLWithPath: "/s"), cache: URL(fileURLWithPath: "/c/downloads"))
        XCTAssertEqual(paths.cache.path, "/c/downloads")
        XCTAssertEqual(paths.helpers(version: "1.0").path, "/s/1.0/helpers")
        XCTAssertEqual(paths.builtApp(version: "1.0").path, "/s/1.0/out/NFSMW.app")
        XCTAssertTrue(BuilderPaths().support.path.hasSuffix("Library/Application Support/NFSMW Builder"))
        XCTAssertTrue(BuilderPaths().cache.path.hasSuffix("Library/Caches/NFSMW/downloads"))
        XCTAssertEqual(paths.python.path, "/s/python")
        XCTAssertEqual(paths.pythonExecutable.path, "/s/python/bin/python3")
        XCTAssertEqual(paths.workspace(version: "1.0").path, "/s/1.0")
        XCTAssertEqual(paths.venvPython(version: "1.0").path, "/s/1.0/.venv/bin/python")
    }

    func testStaleOrHalfCopiedWorkspaceIsReplaced() throws {
        let src = tmp.appendingPathComponent("src"), dst = tmp.appendingPathComponent("dst")
        try write("new", to: src.appendingPathComponent("tools/a.py"))
        try write("old", to: dst.appendingPathComponent("tools/a.py"))
        try write("0.9", to: dst.appendingPathComponent(".builder-version"))
        try prepareWorkspace(sources: src, destination: dst, version: "1.0")
        XCTAssertEqual(read(dst.appendingPathComponent("tools/a.py")), "new")
        XCTAssertEqual(read(dst.appendingPathComponent(".builder-version")), "1.0")

        // No marker (crash mid-copy) is also replaced.
        try fm.removeItem(at: dst.appendingPathComponent(".builder-version"))
        try write("junk", to: dst.appendingPathComponent("tools/a.py"))
        try prepareWorkspace(sources: src, destination: dst, version: "1.0")
        XCTAssertEqual(read(dst.appendingPathComponent("tools/a.py")), "new")

        // Same version with marker: nothing is copied.
        try write("kept", to: dst.appendingPathComponent("tools/a.py"))
        try prepareWorkspace(sources: src, destination: dst, version: "1.0")
        XCTAssertEqual(read(dst.appendingPathComponent("tools/a.py")), "kept")
        let siblings = try fm.contentsOfDirectory(atPath: tmp.path).sorted()
        XCTAssertEqual(siblings, ["dst", "src"])
    }

    func testWorkspaceWithOnlyMarkerIsCopiedAgain() throws {
        let src = tmp.appendingPathComponent("src"), dst = tmp.appendingPathComponent("dst")
        try write("new", to: src.appendingPathComponent("tools/a.py"))
        try write("x", to: src.appendingPathComponent("build.sh"))
        try write("1.0", to: dst.appendingPathComponent(".builder-version"))
        try write("x", to: dst.appendingPathComponent("build.sh"))
        try prepareWorkspace(sources: src, destination: dst, version: "1.0")
        XCTAssertEqual(read(dst.appendingPathComponent("tools/a.py")), "new")
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: tmp.path).sorted(), ["dst", "src"])
    }

    func testSweepRemovesOnlyLeftovers() throws {
        let paths = BuilderPaths(support: tmp)
        for name in [".trash-1/tools/a.py", ".1.0.tmp-2/build.sh", ".python.tmp-3/python/bin/python3",
                     "python/bin/python3", "1.0/.builder-version"] {
            try write("x", to: tmp.appendingPathComponent(name))
        }
        sweepOldWorkspaces(paths, keeping: "1.0", isLocked: { _ in false })
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: tmp.path).sorted(), ["1.0", "python"])
        XCTAssertEqual(read(paths.pythonExecutable), "x")
    }

    func testOldVersionWorkspacesAreRemoved() throws {
        let paths = BuilderPaths(support: tmp)
        try write("0.9", to: tmp.appendingPathComponent("0.9/.builder-version"))
        try write("x", to: tmp.appendingPathComponent("0.9/tools/a.py"))
        try write("1.0", to: tmp.appendingPathComponent("1.0/.builder-version"))
        try write("x", to: tmp.appendingPathComponent("notes/a.txt"))
        try write("x", to: paths.pythonExecutable)
        let size = allocatedSize(of: tmp.appendingPathComponent("0.9"))
        XCTAssertGreaterThan(size, 0)
        XCTAssertEqual(sweepOldWorkspaces(paths, keeping: "1.0", isLocked: { _ in false }), size)
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: tmp.path).sorted(), ["1.0", "notes", "python"])
    }

    func testMoveToTrashRenamesToHiddenSibling() throws {
        let dir = tmp.appendingPathComponent("1.0")
        try write("x", to: dir.appendingPathComponent("tools/a.py"))
        let trash = try moveToTrash(dir)
        XCTAssertFalse(fm.fileExists(atPath: dir.path))
        XCTAssertTrue(trash.lastPathComponent.hasPrefix(".trash-"))
        XCTAssertEqual(trash.deletingLastPathComponent().path, tmp.path)
        XCTAssertEqual(read(trash.appendingPathComponent("tools/a.py")), "x")
    }

    func testWorkspaceCopiesOnlyBundledEntries() throws {
        let src = tmp.appendingPathComponent("repo"), dst = tmp.appendingPathComponent("ws")
        for entry in ["build.sh", "gen.sh", "requirements.txt", "LICENSE", "tools/a.py", "runtime/r.c",
                      "third_party/x/LICENSE", "helpers/innoextract", "gen/big.bin", "out/o.bin",
                      ".venv/bin/python", "tools/__pycache__/x.pyc", "runtime/__pycache__/y.pyc", "README.md",
                      "tests/t.py", "builder/Package.swift"] {
            try write("x", to: src.appendingPathComponent(entry))
        }
        XCTAssertEqual(bundledSourceEntries, ["build.sh", "gen.sh", "requirements.txt", "LICENSE", "tools", "runtime",
                                              "third_party", "helpers"])
        let value = Array("0081;00000000;Test;".utf8)
        let quarantined = src.appendingPathComponent("tools/a.py")
        XCTAssertEqual(setxattr(quarantined.path, "com.apple.quarantine", value, value.count, 0, 0), 0)
        try prepareWorkspace(sources: src, destination: dst, version: "2")
        errno = 0
        XCTAssertEqual(getxattr(dst.appendingPathComponent("tools/a.py").path, "com.apple.quarantine", nil, 0, 0, 0), -1)
        XCTAssertEqual(errno, ENOATTR)
        let top = try fm.contentsOfDirectory(atPath: dst.path).sorted()
        XCTAssertEqual(top, [".builder-version", "LICENSE", "build.sh", "gen.sh", "helpers", "requirements.txt",
                             "runtime", "third_party", "tools"])
        XCTAssertFalse(fm.fileExists(atPath: dst.appendingPathComponent("tools/__pycache__").path))
        XCTAssertFalse(fm.fileExists(atPath: dst.appendingPathComponent("runtime/__pycache__").path))
        XCTAssertTrue(fm.fileExists(atPath: dst.appendingPathComponent("tools/a.py").path))
    }

    func testPythonPinLooksSane() {
        XCTAssertTrue(PythonRuntime.url.absoluteString.hasPrefix("https://github.com/astral-sh/python-build-standalone/releases/download/"))
        XCTAssertTrue(PythonRuntime.url.absoluteString.hasSuffix("aarch64-apple-darwin-install_only.tar.gz"))
        XCTAssertEqual(PythonRuntime.sha256.count, 64)
    }

    private func installResult(_ paths: BuilderPaths, sha: String? = nil,
                               download: (URL, @escaping (Result<URL, Error>) -> Void) -> Void) -> Result<Void, Error> {
        var result: Result<Void, Error>?
        let done = expectation(description: "install")
        PythonRuntime.install(paths, sha256: sha ?? PythonRuntime.sha256, download: download) {
            result = $0
            done.fulfill()
        }
        wait(for: [done], timeout: 30)
        return result!
    }

    func testPythonInstallRejectsBadChecksumAndLeavesNothing() throws {
        let support = tmp.appendingPathComponent("support")
        try fm.createDirectory(at: support, withIntermediateDirectories: true)
        let paths = BuilderPaths(support: support)
        let bad = tmp.appendingPathComponent("bad.tgz")
        try write("not python", to: bad)
        let result = installResult(paths) { _, done in done(.success(bad)) }
        guard case .failure(let error) = result else { return XCTFail("expected failure") }
        XCTAssertTrue("\(error.localizedDescription)".lowercased().contains("checksum"))
        XCTAssertFalse(fm.fileExists(atPath: paths.python.path))
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: support.path), [])
        XCTAssertFalse(PythonRuntime.isInstalled(paths))
    }

    func testPythonInstallReportsDownloadFailure() throws {
        let support = tmp.appendingPathComponent("support")
        try fm.createDirectory(at: support, withIntermediateDirectories: true)
        let paths = BuilderPaths(support: support)
        let result = installResult(paths) { _, done in done(.failure(URLError(.notConnectedToInternet))) }
        guard case .failure(let error) = result else { return XCTFail("expected failure") }
        XCTAssertEqual((error as? URLError)?.code, .notConnectedToInternet)
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: support.path), [])
    }

    func testPythonInstallExtractsVerifiedArchive() throws {
        let support = tmp.appendingPathComponent("support")
        let paths = BuilderPaths(support: support)
        let stage = tmp.appendingPathComponent("stage")
        let exe = stage.appendingPathComponent("python/bin/python3")
        try write("#!/bin/sh\n", to: exe)
        try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: exe.path)
        let archive = tmp.appendingPathComponent("py.tar.gz")
        let tar = Process()
        tar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
        tar.arguments = ["-czf", archive.path, "-C", stage.path, "python"]
        try tar.run()
        tar.waitUntilExit()
        let sha = try sha256Hex(of: archive)
        let result = installResult(paths, sha: sha) { _, done in done(.success(archive)) }
        guard case .success = result else { return XCTFail("\(result)") }
        XCTAssertTrue(fm.isExecutableFile(atPath: paths.pythonExecutable.path))
        XCTAssertEqual(read(paths.python.appendingPathComponent(".nfsmw-python-sha256")), sha)
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: support.path), ["python"])
    }

    private func fakePython(_ paths: BuilderPaths, marker: String?) throws {
        try write("#!/bin/sh\n", to: paths.pythonExecutable)
        try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: paths.pythonExecutable.path)
        if let marker = marker { try write(marker, to: paths.python.appendingPathComponent(".nfsmw-python-sha256")) }
    }

    func testIsInstalledRequiresPinnedMarker() throws {
        let paths = BuilderPaths(support: tmp)
        try fakePython(paths, marker: nil)
        XCTAssertFalse(PythonRuntime.isInstalled(paths))
        try fakePython(paths, marker: "oldpin")
        XCTAssertFalse(PythonRuntime.isInstalled(paths))
        try fakePython(paths, marker: PythonRuntime.sha256)
        XCTAssertTrue(PythonRuntime.isInstalled(paths))
    }

    func testBuildToolsBlockedUntilPythonAndVenvMatch() throws {
        let paths = BuilderPaths(support: tmp)
        let ws = paths.workspace(version: "1")
        let req = ws.appendingPathComponent("requirements.txt")
        try write("numpy\n", to: req)
        try write("", to: paths.venvPython(version: "1"))
        try write(try sha256Hex(of: req) + "\n", to: ws.appendingPathComponent(".venv/.build-requirements-sha256"))
        // Venv fine, Python missing.
        XCTAssertEqual(buildToolsCheck(paths: paths, version: "1"), .blocked("about 90 MB download"))
        try fakePython(paths, marker: PythonRuntime.sha256)
        XCTAssertTrue(buildToolsCheck(paths: paths, version: "1").isReady)
        // Python present, hash mismatch: only the packages are fetched again.
        let packages = CheckState.blocked("Packages need to be set up again (small download)")
        try write("numpy\nscipy\n", to: req)
        XCTAssertEqual(buildToolsCheck(paths: paths, version: "1"), packages)
        // Python present, venv removed (Remove build files).
        try fm.removeItem(at: ws.appendingPathComponent(".venv"))
        XCTAssertEqual(buildToolsCheck(paths: paths, version: "1"), packages)
    }

    func testInstallCompletionArrivesOnMainThread() throws {
        let paths = BuilderPaths(support: tmp.appendingPathComponent("support"))
        let bad = tmp.appendingPathComponent("bad.tgz")
        try write("x", to: bad)
        var onMain: Bool?
        let done = expectation(description: "install")
        PythonRuntime.install(paths, download: { _, finish in
            DispatchQueue.global().async { finish(.success(bad)) }
        }, completion: { _ in
            onMain = Thread.isMainThread
            done.fulfill()
        })
        wait(for: [done], timeout: 30)
        XCTAssertEqual(onMain, true)
    }

    func testRemoveQuarantineRecursive() throws {
        let dir = tmp.appendingPathComponent("q")
        let file = dir.appendingPathComponent("sub/f.txt")
        try write("x", to: file)
        let value = Array("0081;00000000;Test;".utf8)
        for url in [dir, file] {
            XCTAssertEqual(setxattr(url.path, "com.apple.quarantine", value, value.count, 0, 0), 0)
        }
        try removeQuarantine(at: dir)
        for url in [dir, file] {
            errno = 0
            XCTAssertEqual(getxattr(url.path, "com.apple.quarantine", nil, 0, 0, 0), -1)
            XCTAssertEqual(errno, ENOATTR)
        }
        // No attribute present: still fine.
        try removeQuarantine(at: dir)
    }

    func testWorkspaceIsExcludedFromBackup() throws {
        let src = tmp.appendingPathComponent("src"), support = tmp.appendingPathComponent("support")
        try write("x", to: src.appendingPathComponent("build.sh"))
        let dst = support.appendingPathComponent("1.0")
        try prepareWorkspace(sources: src, destination: dst, version: "1.0")
        for url in [dst, support] {
            XCTAssertEqual(try url.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)
        }
    }

    func testSweepSkipsLockedWorkspace() throws {
        let paths = BuilderPaths(support: tmp)
        try write("0.9", to: tmp.appendingPathComponent("0.9/.builder-version"))
        let lock = tmp.appendingPathComponent("0.9/out/app-build.lock")
        try write("", to: lock)
        let fd = open(lock.path, O_RDWR)
        XCTAssertEqual(flock(fd, LOCK_EX), 0)
        XCTAssertTrue(workspaceIsLocked(tmp.appendingPathComponent("0.9")))
        XCTAssertEqual(sweepOldWorkspaces(paths, keeping: "1.0"), 0)
        XCTAssertTrue(fm.fileExists(atPath: tmp.appendingPathComponent("0.9").path))
        close(fd)
        XCTAssertFalse(workspaceIsLocked(tmp.appendingPathComponent("0.9")))
        sweepOldWorkspaces(paths, keeping: "1.0")
        XCTAssertFalse(fm.fileExists(atPath: tmp.appendingPathComponent("0.9").path))
    }

    private func helpersFolder(_ paths: BuilderPaths, version: String) throws -> URL {
        let helpers = paths.helpers(version: version)
        var manifest: [String: Any] = [:]
        for name in ["innoextract", "rtpatch-decode"] {
            let binary = helpers.appendingPathComponent(name)
            try write("binary " + name, to: binary)
            manifest[name] = ["sha256": try sha256Hex(of: binary), "source_sha256": "x"]
        }
        try JSONSerialization.data(withJSONObject: manifest).write(to: helpers.appendingPathComponent("helpers.json"))
        return helpers
    }

    func testChangedHelperBlocksBuildTools() throws {
        let paths = BuilderPaths(support: tmp)
        let ws = paths.workspace(version: "1")
        let req = ws.appendingPathComponent("requirements.txt")
        try write("capstone\n", to: req)
        try write("", to: paths.venvPython(version: "1"))
        try write(try sha256Hex(of: req), to: ws.appendingPathComponent(".venv/.build-requirements-sha256"))
        try fakePython(paths, marker: PythonRuntime.sha256)
        XCTAssertTrue(buildToolsCheck(paths: paths, version: "1").isReady)
        XCTAssertEqual(buildToolsCheck(paths: paths, version: "1", requireHelpers: true), .blocked(incompleteBuilderMessage))
        let helpers = try helpersFolder(paths, version: "1")
        XCTAssertTrue(buildToolsCheck(paths: paths, version: "1", requireHelpers: true).isReady)
        try write("Binary innoextract", to: helpers.appendingPathComponent("innoextract"))
        XCTAssertEqual(buildToolsCheck(paths: paths, version: "1"),
                       .blocked("This copy of NFSMW Builder is incomplete. Download it again."))
        try fm.removeItem(at: helpers.appendingPathComponent("rtpatch-decode"))
        XCTAssertEqual(buildToolsCheck(paths: paths, version: "1"), .blocked(incompleteBuilderMessage))
    }

    func testRemoveBuildFilesKeepsSourcesAndPackages() throws {
        let paths = BuilderPaths(support: tmp)
        let ws = paths.workspace(version: "1")
        for entry in ["tools/a.py", "helpers/innoextract", ".venv/bin/python", ".builder-version", "out/NFSMW.app/x",
                      "gen/all/a.c", "stray.log"] {
            try write(String(repeating: "x", count: 5000), to: ws.appendingPathComponent(entry))
        }
        let size = buildFilesSize(paths, version: "1")
        XCTAssertGreaterThan(size, 0)
        XCTAssertEqual(removeBuildFiles(paths, version: "1"), size)
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: ws.path).sorted(), [".builder-version", ".venv", "helpers", "tools"])
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: tmp.path).sorted(), ["1"])
        XCTAssertEqual(buildFilesSize(paths, version: "1"), 0)
    }
}
