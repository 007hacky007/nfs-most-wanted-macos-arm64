import AppKit
import BuilderCore
import SwiftUI

struct BuildView: View {
    @ObservedObject var model: BuilderModel
    @State private var showDetails = false

    private var currentIndex: Int? { buildSteps.firstIndex { $0.id == model.buildStep } }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Building NFSMW.app")
                .font(.title2)
                .fontWeight(.semibold)
            VStack(alignment: .leading, spacing: 5) {
                ForEach(Array(buildSteps.enumerated()), id: \.offset) { index, step in
                    StepRow(name: name(of: step.id), status: status(of: index))
                }
            }
            ProgressView(value: model.buildFraction)
            HStack {
                Text(detailLine).font(.callout).foregroundColor(.secondary)
                Spacer()
                if let started = model.buildStarted {
                    TimelineView(.periodic(from: started, by: 1)) { context in
                        Text(Self.elapsed(context.date.timeIntervalSince(started)))
                            .font(.callout.monospacedDigit())
                            .foregroundColor(.secondary)
                    }
                }
            }
            Text("This takes about 25 minutes, longer on the first build while Most Wanted HQ downloads. "
                 + "You can keep using your Mac.")
                .font(.caption)
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            DisclosureGroup("Show details", isExpanded: $showDetails) {
                LogView(lines: model.buildLog)
            }
            HStack {
                Spacer()
                Button("Cancel", action: model.cancelBuild)
                    .keyboardShortcut(.cancelAction)
                    .disabled(model.cancelDisabled)
            }
        }
    }

    /// The runtime step shows its round, "round 2 of at most 12".
    private func name(of id: String) -> String {
        if id == model.buildStep, id == "runtime", let round = model.buildStepTitle.range(of: "round ") {
            return (buildStepNames[id] ?? id) + ", " + model.buildStepTitle[round.lowerBound...]
        }
        return buildStepNames[id] ?? id
    }

    private var detailLine: String {
        if let progress = model.installProgress, progress.total > 0 {
            return "Installing NFSMW.app, \(gigabytes(progress.copied)) of \(gigabytes(progress.total))"
        }
        if model.buildStep == "downloads", model.downloadBytes != nil {
            return model.downloadText(prefix: "Downloaded")
        }
        return model.buildStepTitle
    }

    private func status(of index: Int) -> StepRow.Status {
        guard let current = currentIndex else { return .pending }
        if index < current { return .done }
        return index == current ? .current : .pending
    }

    static func elapsed(_ seconds: TimeInterval) -> String {
        let total = Int(seconds)
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

struct StepRow: View {
    enum Status { case done, current, pending }
    let name: String
    let status: Status

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundColor(color)
                .frame(width: 18)
            Text(name)
                .fontWeight(status == .current ? .semibold : .regular)
                .foregroundColor(status == .pending ? .secondary : .primary)
        }
    }

    private var icon: String {
        switch status {
        case .done: return "checkmark.circle.fill"
        case .current: return "arrow.right.circle.fill"
        case .pending: return "circle"
        }
    }

    private var color: Color {
        switch status {
        case .done: return Color(NSColor.systemGreen)
        case .current: return .accentColor
        case .pending: return .secondary
        }
    }
}

/// The pipeline output, scrolled to the end. Only the tail is drawn; Copy log copies everything.
struct LogView: View {
    let lines: [String]
    private static let shownLines = 500

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(lines.suffix(Self.shownLines).joined(separator: "\n"))
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(6)
                    Color.clear.frame(height: 1).id("end")
                }
            }
            .frame(height: 170)
            .background(Color(NSColor.textBackgroundColor))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color(NSColor.separatorColor)))
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }
            .onChange(of: lines.count) { _ in proxy.scrollTo("end", anchor: .bottom) }
        }
    }
}
