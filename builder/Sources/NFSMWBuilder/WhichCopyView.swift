import AppKit
import BuilderCore
import SwiftUI

/// "Which copy works?": the required release, the accepted discs and folder with exact sizes and
/// SHA-256 values (all from tools/game_checksums.json), and what the check found in this copy.
struct WhichCopyView: View {
    @ObservedObject var model: BuilderModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Which copy works?").font(.title2).fontWeight(.semibold)
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if let copies = model.accepted {
                        accepted(copies)
                    } else if model.acceptedFailed {
                        Text("Could not load the list of accepted copies.").foregroundColor(.secondary)
                    } else if model.toolsReady {
                        ProgressView().frame(maxWidth: .infinity)
                    } else {
                        Text("Install the build tools first; the list comes from them.").foregroundColor(.secondary)
                    }
                    if let report = model.gameReport, !report.ok {
                        yourCopy(report)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 460)
            HStack {
                Link("Full list of checksums", destination: model.checksumsURL)
                Spacer()
                if let text = copyText {
                    Button("Copy details") { copyToPasteboard(text) }
                }
                Button("Close") { dismiss() }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 600)
        .onAppear(perform: model.loadAccepted)
    }

    private var copyText: String? {
        let parts = [model.accepted?.plainText, model.gameDetails.map { "Your copy:\n" + $0 }].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: "\n\n")
    }

    @ViewBuilder
    private func accepted(_ copies: AcceptedCopies) -> some View {
        Text("NFSMW Builder needs \(copies.release).").fixedSize(horizontal: false, vertical: true)
        Text("These do not work: \(copies.notSupported.joined(separator: ", ")).")
            .foregroundColor(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        Text("The 4 original CDs (ISO or BIN/CUE)").fontWeight(.semibold).padding(.top, 4)
        ForEach(copies.discs, id: \.sha256) { disc in
            entry("Disc \(disc.disc): \(disc.archive), \(bytes(disc.size))", disc.sha256)
        }
        Text("Together \(bytes(copies.discsTotal)). " + AcceptedCopies.checksumNote)
            .font(.callout)
            .foregroundColor(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        Text("An installed game folder").fontWeight(.semibold).padding(.top, 4)
        Text("\(copies.folder.requiredFiles.formatted()) required files: \(bytes(copies.folder.totalOriginal)) "
             + "as installed from the discs, or \(bytes(copies.folder.totalOfficial)) with the official 1.3 files. "
             + "speed.exe must be one of:")
            .fixedSize(horizontal: false, vertical: true)
        ForEach(copies.folder.executables, id: \.sha256) { exe in
            entry("\(exe.label), \(bytes(exe.size))", exe.sha256)
        }
    }

    @ViewBuilder
    private func yourCopy(_ report: GameReport) -> some View {
        Text("Your copy").fontWeight(.semibold).padding(.top, 8)
        Text(report.message).fixedSize(horizontal: false, vertical: true)
        if !report.problems.isEmpty {
            Text("\(report.failed.formatted()) of \(report.checked.formatted()) checked files are missing or different"
                 + (report.failed > report.problems.count ? "; the first \(report.problems.count):" : ":"))
                .font(.callout)
            ForEach(Array(report.problems.enumerated()), id: \.offset) { _, problem in
                VStack(alignment: .leading, spacing: 2) {
                    Text(problem.path).fontWeight(.medium)
                    Text("Found: " + found(problem.found))
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                    ForEach(problem.accepted, id: \.sha256) { file in
                        Text("Accepted: \(file.size) bytes, \(file.sha256)")
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                            .foregroundColor(.secondary)
                    }
                }
                .padding(.leading, 12)
            }
        }
    }

    private func found(_ found: GameProblem.Found) -> String {
        switch found {
        case .missing: return "missing"
        case let .file(digest): return "\(digest.size) bytes, \(digest.sha256)"
        case let .text(text): return text
        }
    }

    private func entry(_ title: String, _ sha256: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
            Text(sha256)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .foregroundColor(.secondary)
        }
        .padding(.leading, 12)
    }

    private func bytes(_ count: Int64) -> String {
        "\(count.formatted()) bytes"
    }
}
