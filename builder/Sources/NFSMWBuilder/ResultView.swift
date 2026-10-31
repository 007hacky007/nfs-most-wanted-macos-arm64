import AppKit
import BuilderCore
import SwiftUI

struct ResultView: View {
    enum Outcome {
        case success(URL)
        case failure(step: String, message: String)
        case quitToInstall
    }

    @ObservedObject var model: BuilderModel
    let outcome: Outcome
    @State private var showLog = true

    var body: some View {
        switch outcome {
        case let .success(app): success(app)
        case let .failure(step, message): failure(step: step, message: message)
        case .quitToInstall: quitToInstall
        }
    }

    private var quitToInstall: some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48))
                .foregroundColor(Color(NSColor.systemOrange))
            Text("NFSMW is running").font(.title).fontWeight(.semibold)
            Text("Quit NFSMW, then click Install again.")
                .foregroundColor(.secondary)
            HStack {
                Button("Back", action: model.backToChecklist)
                Button("Install again", action: model.installAgain)
                    .keyboardShortcut(.defaultAction)
            }
            .controlSize(.large)
            Spacer()
        }
        .frame(maxWidth: .infinity, minHeight: 430)
    }

    private func success(_ app: URL) -> some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 56))
                .foregroundColor(Color(NSColor.systemGreen))
            Text("Ready").font(.title).fontWeight(.semibold)
            Text("NFSMW.app is in \(app.deletingLastPathComponent().path).")
                .foregroundColor(.secondary)
            HStack {
                Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([app]) }
                Button("Play") { NSWorkspace.shared.open(app) }
                    .keyboardShortcut(.defaultAction)
            }
            .controlSize(.large)
            Spacer()
            if model.cleaningUp {
                Text("Removing build files...").font(.caption).foregroundColor(.secondary)
            } else if let freed = model.freedBytes {
                Text("Build files removed, \(gigabytes(freed)) freed. Python and the downloads are kept for the next build.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            if model.ownsCache && !model.cleaningUp {
                if model.downloadsRemoved {
                    Text("Downloads removed").font(.caption).foregroundColor(.secondary)
                } else {
                    Button("Remove downloads (\(gigabytes(model.cachedBytes)))", action: model.removeDownloads)
                        .controlSize(.small)
                        .help("Frees the downloaded patches and Most Wanted HQ. A new build downloads them again.")
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 430)
    }

    private func failure(step: String, message: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "xmark.octagon.fill")
                    .font(.system(size: 28))
                    .foregroundColor(Color(NSColor.systemRed))
                Text("\(step) failed").font(.title2).fontWeight(.semibold)
            }
            Text(message).fixedSize(horizontal: false, vertical: true)
            DisclosureGroup("Details", isExpanded: $showLog) {
                LogView(lines: model.buildLog)
            }
            HStack {
                Button("Copy log") { copyToPasteboard(model.copyableLog) }
                if model.gameReport.map({ !$0.ok }) == true {
                    Button("Which copy works?") { model.showingWhichCopy = true }
                }
                if model.buildFilesBytes > 0 {
                    Button("Remove build files (\(gigabytes(model.buildFilesBytes)))", action: model.removeBuildFilesAfterFailure)
                }
                Spacer()
                Button("Try again", action: model.tryAgain)
                    .keyboardShortcut(.defaultAction)
            }
        }
        .sheet(isPresented: $model.showingWhichCopy) { WhichCopyView(model: model) }
    }
}
