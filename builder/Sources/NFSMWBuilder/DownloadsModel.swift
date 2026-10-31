import AppKit
import BuilderCore

/// The Downloads row: the official patch, WidescreenFix and the 3.34 GB Most Wanted HQ package.
extension BuilderModel {
    static let downloadsTotal: Int64 = 3_359_162_163
    static let hqPage = URL(string: "https://www.moddb.com/downloads/start/233611")!

    static func downloadsPending(_ status: DownloadsStatus?) -> CheckState {
        guard let status = status else { return .automatic("\(gigabytes(downloadsTotal)), downloaded during the build") }
        if status.isReady { return .ready("Ready") }
        if let partial = status.partialBytes["mw-hq"], partial > 0 {
            return .automatic("\(gigabytes(status.cachedBytes)) of \(gigabytes(status.totalBytes)) downloaded, "
                + "continues where it stopped")
        }
        return .automatic("\(gigabytes(status.remainingBytes)), downloaded during the build")
    }

    /// The Builder's own cache can be removed from the result screen; a cache the user set
    /// with NFSMW_CACHE_DIR is theirs and is never removed.
    var ownsCache: Bool { PipelineRunner.cacheDirectory(paths) == paths.cache }

    func refreshDownloads() {
        guard toolsReady else {
            states[.downloads] = Self.downloadsPending(nil)
            return
        }
        guard statusRunner == nil, downloadRunner == nil else { return }
        let runner = PipelineRunner.downloadsStatus(paths: paths, version: version)
        statusRunner = runner
        var result: DownloadsStatus?
        run(runner, onEvent: { if case let .downloads(status) = $0 { result = status } },
            onExit: { [self] _ in
                statusRunner = nil
                guard downloadRunner == nil else { return }
                downloadsStatus = result
                states[.downloads] = Self.downloadsPending(result)
                refreshDiskSpace()
            })
    }

    var downloading: Bool { downloadRunner != nil }

    func fetchDownloads() {
        guard toolsReady, downloadRunner == nil, phase == .checklist else { return }
        statusRunner?.cancel()
        startDownload(.fetchDownloads(paths: paths, version: version), action: "Downloading")
    }

    func importDownload(_ file: URL) {
        guard toolsReady, downloadRunner == nil, phase == .checklist else { return }
        statusRunner?.cancel()
        startDownload(.importDownload(paths: paths, version: version, file: file), action: "Checking \(file.lastPathComponent)")
    }

    private func startDownload(_ runner: PipelineRunner, action: String) {
        downloadRunner = runner
        downloadBytes = nil
        downloadSpeed = nil
        downloadSample = nil
        states[.downloads] = .checking("\(action)...")
        beginActivity("Downloading the NFSMW patches")
        var ready = false
        var failure: String?
        run(runner, onEvent: { [self] event in
            switch event {
            case let .download(_, received, total):
                noteDownload(received: received, total: total)
                states[.downloads] = .checking(downloadText(prefix: "Downloading"))
            case .downloadsReady: ready = true
            case let .error(message, _): failure = message
            default: break
            }
        }, onExit: { [self] status in
            downloadRunner = nil
            downloadBytes = nil
            if status == 0 && ready {
                downloadFailures = 0
            } else {
                downloadFailures += 1
                notice = Self.plain(failure.map(Self.plainDownloadError)
                    ?? "The download stopped. Click Download now to continue where it stopped.")
            }
            refreshDownloads()
            notifyIfIdle()
        })
    }

    /// The pipeline's sentence says "click Try again" (the build's button); here the button is Download now.
    static func plainDownloadError(_ message: String) -> String {
        message.replacingOccurrences(of: "click Try again", with: "click Download now")
    }

    func noteDownload(received: Int64, total: Int64) {
        downloadBytes = (received, total)
        let now = Date()
        if let sample = downloadSample {
            let seconds = now.timeIntervalSince(sample.date)
            if seconds >= 2 {
                let speed = Double(received - sample.bytes) / seconds
                downloadSpeed = downloadSpeed.map { $0 * 0.7 + speed * 0.3 } ?? speed
                downloadSample = (now, received)
            }
        } else {
            downloadSample = (now, received)
        }
    }

    /// "Downloading 1.2 of 3.4 GB, 5.3 MB/s, about 9 minutes left".
    func downloadText(prefix: String) -> String {
        guard let bytes = downloadBytes else { return "\(prefix)..." }
        var text = "\(prefix) \(gigabytes(bytes.received)) of \(gigabytes(bytes.total))"
        if let speed = downloadSpeed, speed > 1000 {
            text += String(format: ", %.1f MB/s", speed / 1_000_000)
            let minutes = Int((Double(bytes.total - bytes.received) / speed / 60).rounded(.up))
            text += minutes <= 1 ? ", about a minute left" : ", about \(minutes) minutes left"
        }
        return text
    }

    /// Frees the download cache from the result screen.
    func removeDownloads() {
        guard ownsCache, !hasRunningWork else { return }
        let cache = paths.cache
        background({
            for name in (try? FileManager.default.contentsOfDirectory(atPath: cache.path)) ?? [] {
                try? FileManager.default.removeItem(at: cache.appendingPathComponent(name))
            }
        }, then: { [self] in
            downloadsRemoved = true
            downloadsStatus = nil
        })
    }

    var cachedBytes: Int64 { allocatedSize(of: PipelineRunner.cacheDirectory(paths)) }
}
