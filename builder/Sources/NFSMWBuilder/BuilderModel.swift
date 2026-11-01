import AppKit
import BuilderCore

/// Owns the checklist state and runs the pipeline commands. The build, the downloads and the
/// build tools live in extensions (BuildSession.swift, DownloadsModel.swift, ToolsModel.swift).
final class BuilderModel: ObservableObject {
    enum Phase: Equatable {
        case checklist
        case building
        case finished(URL)
        case failed(step: String, message: String)
        /// The build finished but NFSMW is running; installing waits until the user quits it.
        case quitToInstall(built: URL)
    }

    @Published var states: [CheckID: CheckState]
    @Published var phase: Phase = .checklist
    @Published private(set) var gamePaths: [URL]
    @Published private(set) var destination: URL
    /// A plain message shown as an alert over the window.
    @Published var notice: String?

    // Build tools row.
    @Published var setupDetails: String?

    // Game copy row.
    @Published var gameReport: GameReport?
    /// An NFSMW.app found at start; while it is the game copy, the build updates it.
    @Published private(set) var existingApp: URL?
    /// Shown in an empty game row when the game inside the found app could not be reused.
    @Published var gameNote: String?
    /// The game copy the user chose last time, used when the found app's game cannot be reused.
    var savedGamePaths: [URL] = []
    @Published var showingWhichCopy = false
    @Published var accepted: AcceptedCopies?
    @Published var acceptedFailed = false

    // Downloads row.
    @Published var downloadsStatus: DownloadsStatus?
    @Published var downloadFailures = 0
    @Published var downloadBytes: (received: Int64, total: Int64)?
    @Published var downloadSpeed: Double?

    // Build view and result.
    @Published var buildStep = ""
    @Published var buildStepTitle = ""
    @Published var buildFraction = 0.0
    @Published var buildLog: [String] = []
    @Published var buildStarted: Date?
    @Published var cancelDisabled = false
    @Published var installProgress: (copied: Int64, total: Int64)?
    @Published var freedBytes: Int64?
    @Published var cleaningUp = false
    @Published var downloadsRemoved = false
    @Published var failureLogFile: String?
    /// Files a cancelled, failed or not installed build left in the workspace.
    @Published var buildFilesBytes: Int64 = 0
    @Published var removingBuildFiles = false
    /// Counts size measurements of the build files; see refreshBuildFiles.
    var buildFilesGeneration = 0

    let paths = BuilderPaths()
    let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0-dev"
    let sources = BuilderModel.findSources()
    /// A bundle built by tools/make_builder.py; only then are the helpers required.
    let isReleaseBundle = Bundle.main.bundleURL.pathExtension == "app"
    let defaults = UserDefaults.standard

    var live: [ObjectIdentifier: PipelineRunner] = [:]
    var idleHandlers: [() -> Void] = []
    var shuttingDown = false
    var workspaceReady = false
    var installingTools = false
    var downloadTask: URLSessionDownloadTask?
    var downloadProgress: NSKeyValueObservation?
    var cltTimer: Timer?
    var gameRunner: PipelineRunner?
    var checkedGame: [URL]?
    var acceptedRunner: PipelineRunner?
    var statusRunner: PipelineRunner?
    var downloadRunner: PipelineRunner?
    var downloadSample: (date: Date, bytes: Int64)?
    var buildRunner: PipelineRunner?
    var buildError: String?
    var builtApp: URL?
    var userCancelled = false
    var flushScheduled = false
    var pendingLog: [String] = []
    /// Background file work (install, removing files) that a quit must wait for.
    var busyWork = 0
    var activity: NSObjectProtocol?

    init() {
        var initial = Dictionary(uniqueKeysWithValues: CheckID.allCases.map { ($0, CheckState.checking("Checking...")) })
        initial[.downloads] = Self.downloadsPending(nil)
        states = initial
        let saved = UserDefaults.standard
        let chosen = (saved.stringArray(forKey: "gamePaths") ?? []).map { URL(fileURLWithPath: $0) }
        let target = saved.string(forKey: "destination").map { URL(fileURLWithPath: $0) } ?? defaultDestination
        // Updating: the game inside the current NFSMW.app is the game copy unless it fails the check.
        let found = findExistingApp(destination: target)
        destination = target
        existingApp = found
        gamePaths = found.map { [$0] } ?? chosen
        savedGamePaths = chosen
    }

    // MARK: - Checklist

    var toolsReady: Bool { states[.buildTools]?.isReady == true }
    /// Never while old build files are being removed: that removal must not see the new build.
    var buildEnabled: Bool { canBuild(states) && phase == .checklist && !removingBuildFiles }
    var gameRejected: Bool { gameReport != nil && states[.gameCopy].map { if case .blocked = $0 { return true }; return false } == true }

    func start() {
        refresh()
        prepare(sweep: true) { [self] _ in refreshBuildTools() }
    }

    /// Re-evaluates every row. Expensive checks (the game copy) only run again when their input changed.
    func refresh() {
        guard phase == .checklist, !shuttingDown else { return }
        states[.mac] = macCheck(isAppleSilicon: Self.isAppleSilicon, version: ProcessInfo.processInfo.operatingSystemVersion)
        states[.destination] = destinationCheck(destination)
        refreshDiskSpace()
        if workspaceReady && !removingBuildFiles { refreshBuildFiles() }
        refreshCommandLineTools()
        refreshBuildTools()
    }

    func refreshBuildTools() {
        if workspaceReady && !installingTools {
            states[.buildTools] = buildToolsCheck(paths: paths, version: version, requireHelpers: isReleaseBundle)
        }
        refreshDownloads()
        refreshGame()
        if toolsReady { loadAccepted() }
    }

    func refreshCommandLineTools() {
        DispatchQueue.global(qos: .userInitiated).async {
            let state = CommandLineTools().state()
            DispatchQueue.main.async { [self] in
                states[.commandLineTools] = state
                if state.isReady { cltTimer?.invalidate(); cltTimer = nil }
            }
        }
    }

    func installCommandLineTools() {
        DispatchQueue.global(qos: .userInitiated).async { CommandLineTools().startInstall() }
        cltTimer?.invalidate()
        cltTimer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            self?.refreshCommandLineTools()
        }
    }

    func refreshDiskSpace() {
        let workspace = Self.volume(of: paths.support), target = Self.volume(of: destination)
        guard let available = workspace.available, let destinationAvailable = target.available else {
            states[.diskSpace] = .blocked("Could not read the free space on this disk")
            return
        }
        // Leftover build files are removed before the next build starts, so they count as free.
        states[.diskSpace] = diskSpaceCheck(workspaceAvailable: available + buildFilesBytes, workspaceVolume: workspace.name,
                                            destinationAvailable: destinationAvailable, destinationVolume: target.name,
                                            sameVolume: sameVolume(paths.support, destination),
                                            cachedBytes: downloadsStatus?.cachedBytes ?? 0)
    }

    static func volume(of url: URL) -> (name: String, available: Int64?) {
        var probe = url
        while !FileManager.default.fileExists(atPath: probe.path) && probe.path != "/" {
            probe = probe.deletingLastPathComponent()
        }
        let values = try? probe.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey, .volumeLocalizedNameKey])
        return (values?.volumeLocalizedName ?? "this disk", values?.volumeAvailableCapacityForImportantUsage)
    }

    func setDestination(_ url: URL) {
        destination = url
        defaults.set(url.path, forKey: "destination")
        states[.destination] = destinationCheck(url)
        refreshDiskSpace()
    }

    // MARK: - Game copy

    static func isGameCandidate(_ url: URL) -> Bool {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir) else { return false }
        return isDir.boolValue || ["iso", "bin", "cue"].contains(url.pathExtension.lowercased())
    }

    /// Several items may be chosen or dropped together; anything that is neither a folder nor a
    /// disc image is reported instead of silently ignored.
    func setGame(_ urls: [URL]) {
        guard phase == .checklist, !urls.isEmpty else { return }
        let usable = urls.filter(Self.isGameCandidate)
        let skipped = urls.filter { !Self.isGameCandidate($0) }.map(\.lastPathComponent)
        if !skipped.isEmpty {
            notice = "\(skipped.joined(separator: ", ")) \(skipped.count == 1 ? "is" : "are") not a folder, a disc image "
                + "(.iso, .bin or .cue) or NFSMW.app, so \(skipped.count == 1 ? "it was" : "they were") left out."
        }
        guard !usable.isEmpty else { return }
        gamePaths = usable
        gameNote = nil
        defaults.set(usable.map(\.path), forKey: "gamePaths")
        checkedGame = nil
        refreshGame()
    }

    /// The row title: the folder name, or how many images were chosen.
    var gameTitle: String {
        guard !gamePaths.isEmpty else { return "Game copy" }
        if usesApp { return "Game copy: the game inside \(gamePaths[0].lastPathComponent)" }
        if gamePaths.count == 1 { return "Game copy: \(gamePaths[0].lastPathComponent)" }
        return "Game copy: \(gamePaths.count) disc images"
    }

    var gameTooltip: String { gamePaths.map(usesApp ? \.path : \.lastPathComponent).joined(separator: "\n") }

    /// The game copy is an NFSMW.app (found at start, chosen or dropped).
    var usesApp: Bool { gamePaths.count == 1 && gamePaths[0].pathExtension.lowercased() == "app" }

    /// The build replaces the app it reads the game from: an update.
    var updating: Bool {
        usesApp && gamePaths[0].standardizedFileURL.path == destination.appendingPathComponent("NFSMW.app").standardizedFileURL.path
    }

    var buildTitle: String {
        buildButtonTitle(updating: updating, oldVersion: updating ? builderVersion(of: gamePaths[0]) : nil,
                         newVersion: version)
    }

    func refreshGame() {
        guard !gamePaths.isEmpty else {
            gameReport = nil
            states[.gameCopy] = .blocked(gameNote ?? "Choose your game folder, or all four disc images together")
            return
        }
        guard toolsReady else {
            gameRunner?.cancel()
            gameRunner = nil
            checkedGame = nil
            gameReport = nil
            states[.gameCopy] = .checking("Checked once build tools are installed")
            return
        }
        guard checkedGame != gamePaths else { return }
        gameRunner?.cancel()
        let game = gamePaths
        checkedGame = game
        gameReport = nil
        states[.gameCopy] = .checking("Checking your game copy...")
        let runner = PipelineRunner.checkGame(paths: paths, version: version, game: game)
        gameRunner = runner
        var detected: String?
        var kind: String?
        var message: String?
        var report: GameReport?
        run(runner, onEvent: { event in
            switch event {
            case let .game(version, found): (detected, kind) = (version, found)
            case let .gameRejected(text, rejected): (message, report) = (text, rejected)
            case let .error(text, _): message = text
            default: break
            }
        }, onExit: { [self] status in
            guard gameRunner === runner else { return }
            gameRunner = nil
            if status == 0, let detected = detected {
                states[.gameCopy] = .ready(kind == "app" ? "Uses the game inside \(game[0].lastPathComponent): \(detected)"
                                                          : detected)
            } else if let app = existingApp, game == [app] {
                // The app found at start cannot be reused: back to the copy chosen before, or an empty row.
                existingApp = nil
                gameNote = Self.plain(message ?? "The game inside NFSMW.app cannot be reused")
                gamePaths = savedGamePaths
                checkedGame = nil
                refreshGame()
            } else {
                gameReport = report
                states[.gameCopy] = .blocked(Self.plain(message ?? "Could not check this game copy"))
            }
        })
    }

    /// The text behind Copy details on a rejected game copy.
    var gameDetails: String? {
        guard gameRejected, let report = gameReport else { return nil }
        return (["Chosen: " + gamePaths.map(\.lastPathComponent).joined(separator: ", "), report.plainText])
            .joined(separator: "\n")
    }

    func loadAccepted() {
        guard accepted == nil, acceptedRunner == nil, toolsReady else { return }
        let runner = PipelineRunner.acceptedCopies(paths: paths, version: version)
        acceptedRunner = runner
        acceptedFailed = false
        var result: AcceptedCopies?
        run(runner, onEvent: { if case let .accepted(copies) = $0 { result = copies } },
            onExit: { [self] _ in
                acceptedRunner = nil
                accepted = result
                acceptedFailed = result == nil
            })
    }

    var checksumsURL: URL {
        let tag = version.hasSuffix("-dev") ? "master" : "v\(version)"
        return URL(string: "https://github.com/007hacky007/nfs-most-wanted-macos-arm64/blob/\(tag)/tools/game_checksums.json")!
    }

    // MARK: - Processes and shutdown

    var hasRunningWork: Bool { !live.isEmpty || downloadTask != nil || busyWork > 0 }

    func run(_ runner: PipelineRunner, onEvent: @escaping (PipelineEvent) -> Void,
             onExit: @escaping (Int32) -> Void) {
        guard !shuttingDown else { return }
        let key = ObjectIdentifier(runner)
        live[key] = runner
        do {
            try runner.start(onEvent: onEvent, onExit: { [self] status in
                live[key] = nil
                onExit(status)
                notifyIfIdle()
            })
        } catch {
            live[key] = nil
            DispatchQueue.main.async {
                onEvent(.log(error.localizedDescription))
                onExit(-1)
            }
        }
    }

    /// Runs file work off the main queue; a quit waits for it to finish.
    func background(_ work: @escaping () -> Void, then done: @escaping () -> Void) {
        busyWork += 1
        DispatchQueue.global(qos: .userInitiated).async {
            work()
            DispatchQueue.main.async { [self] in
                busyWork -= 1
                done()
                notifyIfIdle()
            }
        }
    }

    /// Keeps the Mac from idle-sleeping while a build, download or import runs.
    func beginActivity(_ reason: String) {
        guard activity == nil else { return }
        activity = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled, .userInitiated], reason: reason)
    }

    func endActivity() {
        guard let token = activity else { return }
        ProcessInfo.processInfo.endActivity(token)
        activity = nil
    }

    /// Cancels every running command and calls `completion` once all of them have exited.
    func stopAll(then completion: @escaping () -> Void) {
        shuttingDown = true
        cltTimer?.invalidate()
        downloadTask?.cancel()
        downloadTask = nil
        idleHandlers.append(completion)
        live.values.forEach { $0.cancel() }
        notifyIfIdle()
    }

    func notifyIfIdle() {
        guard !hasRunningWork else { return }
        endActivity()
        guard !idleHandlers.isEmpty else { return }
        let handlers = idleHandlers
        idleHandlers = []
        handlers.forEach { $0() }
    }

    // MARK: - Helpers

    private static var isAppleSilicon: Bool {
        var value: Int32 = 0
        var size = MemoryLayout<Int32>.size
        return sysctlbyname("hw.optional.arm64", &value, &size, nil, 0) == 0 && value == 1
    }

    /// The bundled sources. Only outside an app bundle (`swift run`) does it fall back to the
    /// repository the executable was built from.
    private static func findSources() -> URL? {
        if let bundled = Bundle.main.resourceURL?.appendingPathComponent("BuildSources"),
           FileManager.default.fileExists(atPath: bundled.appendingPathComponent("build.sh").path) {
            return bundled
        }
        guard Bundle.main.bundleURL.pathExtension != "app",
              var url = Bundle.main.executableURL?.resolvingSymlinksInPath() else { return nil }
        while url.path != "/" {
            url = url.deletingLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("build.sh").path) { return url }
        }
        return nil
    }

    /// Pipeline messages start in lower case; the window shows them as sentences.
    static func plain(_ message: String) -> String {
        message.prefix(1).uppercased() + message.dropFirst()
    }
}
