import Foundation

public protocol CommandRunning {
    func run(_ executable: String, _ arguments: [String]) -> (status: Int32, output: String)
}

public struct SystemCommandRunner: CommandRunning {
    public init() {}

    public func run(_ executable: String, _ arguments: [String]) -> (status: Int32, output: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        do {
            try process.run()
        } catch {
            return (127, "\(error)")
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return (process.terminationStatus, String(decoding: data, as: UTF8.self))
    }
}

/// Detects the Xcode command line tools without ever running the xcrun or clang
/// shims, because those pop up Apple's installer dialog.
public struct CommandLineTools {
    let runner: CommandRunning
    let fileExists: (String) -> Bool

    public init(runner: CommandRunning = SystemCommandRunner(),
                fileExists: @escaping (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) {
        self.runner = runner
        self.fileExists = fileExists
    }

    public func state() -> CheckState {
        let missing = CheckState.blocked("Needed to compile the game on your Mac, about 2 GB from Apple")
        let result = runner.run("/usr/bin/xcode-select", ["-p"])
        let dir = result.output.trimmingCharacters(in: .whitespacesAndNewlines)
        guard result.status == 0, !dir.isEmpty else { return missing }
        let clang = [dir + "/usr/bin/clang",
                     dir + "/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"]
        guard clang.contains(where: fileExists), fileExists("/usr/bin/codesign") else { return missing }
        return .ready("Installed")
    }

    public func startInstall() {
        _ = runner.run("/usr/bin/xcode-select", ["--install"])
    }
}
