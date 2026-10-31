import AppKit
import BuilderCore

/// The workspace copy, the private Python and the Python packages (the Build tools row).
extension BuilderModel {
    /// `sweep` (only on start, when nothing else uses the support folder) first removes other
    /// versions' workspaces and what an interrupted removal or copy left behind.
    func prepare(sweep: Bool = false, _ completion: @escaping (Bool) -> Void) {
        if workspaceReady { return completion(true) }
        guard let sources = sources else {
            states[.buildTools] = .blocked(incompleteBuilderMessage)
            return completion(false)
        }
        states[.buildTools] = .checking("Preparing build files...")
        let (paths, version) = (paths, version)
        var freed: Int64 = 0
        var result: Result<Void, Error> = .success(())
        background({
            if sweep { freed = sweepOldWorkspaces(paths, keeping: version) }
            result = Result {
                try prepareWorkspace(sources: sources, destination: paths.workspace(version: version), version: version)
            }
        }, then: { [self] in
            if freed > 0 { NSLog("NFSMW Builder removed old build files: %@", gigabytes(freed)) }
            if case let .failure(error) = result {
                states[.buildTools] = .blocked("Could not copy the build files: \(error.localizedDescription)")
            } else {
                workspaceReady = true
            }
            completion(workspaceReady)
        })
    }

    func installBuildTools() {
        guard !installingTools, !shuttingDown else { return }
        installingTools = true
        setupDetails = nil
        states[.buildTools] = .checking("Installing...")
        refreshGame()
        prepare { [self] ready in
            guard ready else { installingTools = false; return }
            if PythonRuntime.isInstalled(paths) { runSetup() } else { downloadPython() }
        }
    }

    private func downloadPython() {
        states[.buildTools] = .checking("Downloading Python...")
        PythonRuntime.install(paths, download: { url, done in
            let task = URLSession.shared.downloadTask(with: url) { file, response, error in
                if let file = file, (response as? HTTPURLResponse)?.statusCode == 200 {
                    done(.success(file))
                } else {
                    done(.failure(error ?? URLError(.badServerResponse)))
                }
            }
            var shown = -1
            downloadProgress = task.progress.observe(\.fractionCompleted) { progress, _ in
                let percent = Int(progress.fractionCompleted * 100)
                guard percent != shown else { return }
                shown = percent
                DispatchQueue.main.async { [self] in
                    guard downloadTask === task else { return }
                    states[.buildTools] = .checking(percent >= 100 ? "Unpacking Python..." : "Downloading Python, \(percent)%")
                }
            }
            downloadTask = task
            task.resume()
        }, completion: { [self] result in
            downloadTask = nil
            downloadProgress = nil
            switch result {
            case .success:
                runSetup()
            case let .failure(error):
                let text = error is URLError ? "Could not download Python. Check your internet connection and try again."
                    : Self.plain(error.localizedDescription)
                toolsFailed(text, details: String(describing: error))
            }
            notifyIfIdle()
        })
    }

    private func runSetup() {
        states[.buildTools] = .checking("Setting up build tools...")
        var output: [String] = []
        var error: String?
        run(.setup(paths: paths, version: version), onEvent: { event in
            switch event {
            case let .log(line): output.append(line)
            case let .step(_, title): output.append(title)
            case let .error(message, _):
                error = message
                output.append("Error: \(message)")
            default: break
            }
        }, onExit: { [self] status in
            installingTools = false
            let details = (output + ["Setup exited with status \(status)."]).joined(separator: "\n")
            guard status == 0 else {
                let message = error.map(Self.plain)
                    ?? "Could not set up the build tools. Check your internet connection and try again."
                return toolsFailed(message, details: details)
            }
            refreshBuildTools()
            if !toolsReady { toolsFailed("The build tools are incomplete. Try again.", details: details) }
        })
    }

    private func toolsFailed(_ message: String, details: String? = nil) {
        installingTools = false
        setupDetails = details
        states[.buildTools] = .blocked(message)
        refreshGame()
    }
}
