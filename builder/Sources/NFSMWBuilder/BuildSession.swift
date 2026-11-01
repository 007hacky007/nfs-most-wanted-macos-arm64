import AppKit
import BuilderCore

/// Building, installing the result and cleaning up.
extension BuilderModel {
    func build() {
        guard buildEnabled, !gamePaths.isEmpty, !shuttingDown else { return }
        if isNFSMWRunning() {
            notice = "Quit NFSMW first, then try again."
            return
        }
        gameRunner?.cancel()
        statusRunner?.cancel()
        (buildLog, pendingLog, buildStep, buildStepTitle, buildFraction) = ([], [], "", CleanupText.deletingOld, 0)
        (buildError, builtApp, failureLogFile, installProgress, freedBytes) = (nil, nil, nil, nil, nil)
        (userCancelled, cancelDisabled, downloadsRemoved) = (false, false, false)
        downloadBytes = nil
        downloadSpeed = nil
        downloadSample = nil
        buildStarted = Date()
        phase = .building
        beginActivity("Building NFSMW.app")
        // Nothing from an earlier, cancelled or failed build is reused; clear it so it cannot
        // add to the peak (the Disk row counts these files as free).
        let (paths, version) = (paths, version)
        buildFilesGeneration += 1
        background({ removeBuildFiles(paths, version: version) }, then: { [self] in
            buildFilesBytes = 0
            guard !shuttingDown else { return }
            if userCancelled {
                phase = .checklist
                endActivity()
                return refresh()
            }
            startBuild()
        })
    }

    private func startBuild() {
        buildStepTitle = ""
        let runner = PipelineRunner.build(paths: paths, version: version, game: gamePaths)
        buildRunner = runner
        run(runner, onEvent: { [self] event in
            switch event {
            case let .step(id, title):
                appendLog(title)
                if buildSteps.contains(where: { $0.id == id }) {
                    buildStep = id
                    buildStepTitle = title
                    buildFraction = max(buildFraction, progressFraction(atStart: id) ?? buildFraction)
                }
            case let .download(_, received, total):
                noteDownload(received: received, total: total)
                if total > 0, let fraction = progressFraction(step: "downloads", within: Double(received) / Double(total)) {
                    buildFraction = max(buildFraction, fraction)
                }
            case let .log(line): appendLog(line)
            case let .error(message, log):
                buildError = message
                failureLogFile = log
                appendLog("Error: \(message)")
            case let .gameRejected(message, report):
                buildError = message
                gameReport = report
                appendLog("Error: \(message)")
            case let .done(url): builtApp = url
            default: break
            }
        }, onExit: { [self] status in
            buildRunner = nil
            flushLog()
            if status != 0 { appendLog("The build exited with status \(status).") }
            if shuttingDown { return }
            if userCancelled {
                phase = .checklist
                checkedGame = nil
                refresh()
                // A cancelled build leaves tens of GB that the next build would not reuse.
                return removeBuildFilesNow()
            }
            if status == 0, buildError == nil, let built = builtApp {
                install(built)
            } else {
                fail(step: buildStepNames[buildStep] ?? "Getting ready",
                     message: buildError ?? "The build stopped unexpectedly.")
            }
        })
    }

    func cancelBuild() {
        guard phase == .building, !cancelDisabled else { return }
        userCancelled = true
        cancelDisabled = true
        appendLog("Cancelling...")
        // Before the pipeline starts (old build files are still being removed) the flag is enough.
        buildRunner?.cancel()
    }

    /// Retries only the install of an already built app, after the user quit NFSMW.
    func installAgain() {
        guard case let .quitToInstall(built) = phase else { return }
        install(built)
    }

    /// Leaves the "NFSMW is running" screen. The built app stays in the workspace; the checklist
    /// offers Delete temporary files for it.
    func backToChecklist() {
        guard case .quitToInstall = phase else { return }
        phase = .checklist
        checkedGame = nil
        refresh()
    }

    private func install(_ built: URL) {
        cancelDisabled = true
        if case .quitToInstall = phase {
            guard !isNFSMWRunning() else {
                notice = "NFSMW is still running. Quit it, then click Install again."
                return
            }
            phase = .building
        } else if isNFSMWRunning() {
            appendLog("NFSMW is running, so the new build was not installed yet.")
            phase = .quitToInstall(built: built)
            return
        }
        buildStepTitle = "Installing NFSMW.app"
        appendLog("Installing NFSMW.app into \(destination.path)")
        flushLog()
        let directory = destination
        var result: Result<URL, Error> = .failure(InstallError(message: "Not installed"))
        background({
            // Checked again here in case the game was started since; NSRunningApplication is thread safe.
            result = Result {
                try installApp(built, into: directory, isRunning: isNFSMWRunning, progress: { copied, total in
                    DispatchQueue.main.async { [self] in installProgress = (copied, total) }
                })
            }
        }, then: { [self] in
            installProgress = nil
            switch result {
            case let .success(app):
                cleanUp(after: app)
            case let .failure(error as InstallError) where error.details == nil && isNFSMWRunning():
                appendLog(error.message)
                phase = .quitToInstall(built: built)
            case let .failure(error):
                if let details = (error as? InstallError)?.details { appendLog(details) }
                endActivity()
                fail(step: "Install", message: error.localizedDescription)
            }
        })
    }

    /// Owner decision D3: the tens of GB of build files go away once NFSMW.app is in place.
    private func cleanUp(after app: URL) {
        cleaningUp = true
        phase = .finished(app)
        let (paths, version) = (paths, version)
        var freed: Int64 = 0
        background({ freed = removeBuildFiles(paths, version: version) }, then: { [self] in
            cleaningUp = false
            freedBytes = freed
            endActivity()
        })
    }

    private func fail(step: String, message: String) {
        phase = .failed(step: step, message: Self.plain(message))
        endActivity()
        refreshBuildFiles()
    }

    func tryAgain() {
        phase = .checklist
        checkedGame = nil
        refresh()
    }

    /// Removes what a cancelled, failed or not yet installed build left in the workspace
    /// (renamed aside first, so a quit during the delete leaves nothing half removed).
    func removeBuildFilesNow() {
        guard buildRunner == nil, !removingBuildFiles else { return }
        removingBuildFiles = true
        buildFilesGeneration += 1
        let (paths, version) = (paths, version)
        background({ removeBuildFiles(paths, version: version) }, then: { [self] in
            removingBuildFiles = false
            refreshBuildFiles()
        })
    }

    /// Measures the leftover build files off the main queue, then updates the Disk row.
    /// Only the latest measurement applies: one started before a removal or a newer
    /// measurement finishes too late to matter.
    func refreshBuildFiles() {
        buildFilesGeneration += 1
        let (paths, version, generation) = (paths, version, buildFilesGeneration)
        var size: Int64 = 0
        background({ size = buildFilesSize(paths, version: version) }, then: { [self] in
            guard generation == buildFilesGeneration else { return }
            buildFilesBytes = size
            refreshDiskSpace()
        })
    }

    /// The whole log plus the last 200 lines of the log file the failed step named.
    var copyableLog: String {
        var text = buildLog.joined(separator: "\n")
        if let file = failureLogFile, let contents = try? String(contentsOfFile: file, encoding: .utf8) {
            let tail = contents.split(separator: "\n", omittingEmptySubsequences: false).suffix(200)
            text += "\n\n--- last lines of \((file as NSString).lastPathComponent) ---\n" + tail.joined(separator: "\n")
        }
        return text
    }

    /// Lines arrive faster than SwiftUI should redraw, so they are published at most four times a second.
    func appendLog(_ line: String) {
        pendingLog.append(line)
        guard !flushScheduled else { return }
        flushScheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [self] in flushLog() }
    }

    func flushLog() {
        flushScheduled = false
        guard !pendingLog.isEmpty else { return }
        buildLog += pendingLog
        pendingLog = []
    }
}
