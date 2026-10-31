import AppKit
import BuilderCore
import SwiftUI
import UniformTypeIdentifiers

struct ChecklistView: View {
    @ObservedObject var model: BuilderModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(CheckID.allCases, id: \.self) { id in
                CheckRow(title: title(for: id), tooltip: id == .gameCopy ? model.gameTooltip : nil,
                         state: model.states[id] ?? .checking("Checking..."), buttons: buttons(for: id))
                if id != CheckID.allCases.last { Divider() }
            }
            Button(action: model.build) {
                Text("Build NFSMW.app")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.large)
            .keyboardShortcut(.defaultAction)
            .disabled(!model.buildEnabled)
            .padding(.top, 16)
            Text("The build takes about 25 minutes and needs about 40 GB of free space while it runs. "
                 + "You can keep using your Mac.")
                .font(.caption)
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 8)
        }
        .sheet(isPresented: $model.showingWhichCopy) { WhichCopyView(model: model) }
    }

    private func title(for id: CheckID) -> String {
        id == .gameCopy ? model.gameTitle : id.title
    }

    private func buttons(for id: CheckID) -> [RowButton] {
        let state = model.states[id]
        switch (id, state) {
        case (.commandLineTools, .blocked?):
            return [RowButton(label: "Install...", action: model.installCommandLineTools)]
        case (.buildTools, .blocked?):
            let install = RowButton(label: "Install", action: model.installBuildTools)
            if case .blocked(incompleteBuilderMessage)? = state { return [] }
            guard let details = model.setupDetails else { return [install] }
            return [RowButton(label: "Copy details", action: { copyToPasteboard(details) }), install]
        case (.downloads, .automatic?) where model.toolsReady && !model.downloading:
            var buttons = [RowButton(label: "Download now", action: model.fetchDownloads),
                           RowButton(label: "Use a file I already have...", action: chooseHQFile)]
            if model.downloadFailures >= 2 {
                buttons.append(RowButton(label: "Open the download page", action: {
                    NSWorkspace.shared.open(BuilderModel.hqPage)
                }))
            }
            return buttons
        case (.gameCopy, .blocked?) where model.gameRejected:
            let details = model.gameDetails.map { text in [RowButton(label: "Copy details", action: { copyToPasteboard(text) })] }
            return (details ?? []) + [RowButton(label: "Which copy works?", action: { model.showingWhichCopy = true }),
                                      RowButton(label: "Choose...", action: chooseGame)]
        case (.gameCopy, _):
            return [RowButton(label: "Which copy works?", action: { model.showingWhichCopy = true }),
                    RowButton(label: "Choose...", action: chooseGame)]
        case (.destination, _):
            return [RowButton(label: "Change...", action: chooseDestination)]
        default:
            return []
        }
    }

    private func chooseGame() {
        let panel = NSOpenPanel()
        panel.message = "Choose your game folder, a folder with the four disc images, or all four images together"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = ["iso", "bin", "cue"].compactMap { UTType(filenameExtension: $0) } + [.folder]
        if let current = model.gamePaths.first { panel.directoryURL = current.deletingLastPathComponent() }
        if panel.runModal() == .OK { model.setGame(panel.urls) }
    }

    private func chooseHQFile() {
        let panel = NSOpenPanel()
        panel.message = "Choose MW_HQ_1.20.9.zip. It is checked and copied; your file is not changed."
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.zip]
        if panel.runModal() == .OK, let url = panel.url { model.importDownload(url) }
    }

    private func chooseDestination() {
        let panel = NSOpenPanel()
        panel.message = "Choose where to put NFSMW.app"
        panel.prompt = "Choose"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = model.destination
        if panel.runModal() == .OK, let url = panel.url { model.setDestination(url) }
    }
}

/// Accepts game folders and disc images dropped anywhere on the window, several at once.
struct GameDropTarget: ViewModifier {
    @ObservedObject var model: BuilderModel
    @State private var targeted = false

    func body(content: Content) -> some View {
        content
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.accentColor, lineWidth: 3)
                    .padding(-10)
                    .opacity(targeted ? 1 : 0)
            )
            .onDrop(of: [UTType.fileURL], isTargeted: $targeted, perform: drop)
    }

    private func drop(_ providers: [NSItemProvider]) -> Bool {
        guard model.phase == .checklist, !providers.isEmpty else { return false }
        let group = DispatchGroup()
        let lock = NSLock()
        var urls: [(Int, URL)] = []
        for (index, provider) in providers.enumerated() {
            group.enter()
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                let url = (item as? Data).flatMap { URL(dataRepresentation: $0, relativeTo: nil) } ?? (item as? URL)
                if let url = url {
                    lock.lock()
                    urls.append((index, url))
                    lock.unlock()
                }
                group.leave()
            }
        }
        group.notify(queue: .main) { model.setGame(urls.sorted { $0.0 < $1.0 }.map(\.1)) }
        return true
    }
}

struct RowButton {
    let label: String
    let action: () -> Void
}

func copyToPasteboard(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}

struct CheckRow: View {
    let title: String
    var tooltip: String?
    let state: CheckState
    let buttons: [RowButton]

    /// Up to two buttons sit beside the message; more go on their own line below it, so the
    /// message keeps the width it needs.
    var body: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(state.color)
                .frame(width: 12, height: 12)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).fontWeight(.semibold).help(tooltip ?? "")
                Text(BuilderModel.plain(state.message))
                    .font(.callout)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if buttons.count > 2 {
                    HStack { buttonViews }.padding(.top, 6)
                }
            }
            Spacer(minLength: 8)
            if buttons.count <= 2 { buttonViews }
        }
        .padding(.vertical, 9)
    }

    private var buttonViews: some View {
        ForEach(buttons, id: \.label) { button in
            Button(button.label, action: button.action)
        }
    }
}

extension CheckID {
    var title: String {
        switch self {
        case .mac: return "Mac"
        case .commandLineTools: return "Xcode command line tools"
        case .buildTools: return "Build tools"
        case .downloads: return "Downloads"
        case .gameCopy: return "Game copy"
        case .destination: return "Destination"
        case .diskSpace: return "Free disk space"
        }
    }
}

extension CheckState {
    var color: Color {
        switch self {
        case .checking: return Color(NSColor.systemGray)
        case .ready: return Color(NSColor.systemGreen)
        case .automatic: return Color(NSColor.systemOrange)
        case .blocked: return Color(NSColor.systemRed)
        }
    }
}
