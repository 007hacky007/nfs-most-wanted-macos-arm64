import Foundation

/// A size and SHA-256 pair, exact byte counts of one file.
public struct FileDigest: Decodable, Equatable {
    public let size: Int64
    public let sha256: String

    public init(size: Int64, sha256: String) {
        self.size = size
        self.sha256 = sha256
    }
}

/// One accepted version of a file, as tools/game_checksums.json pins it.
public struct AcceptedFile: Decodable, Equatable {
    public let kind: String
    public let size: Int64
    public let sha256: String
}

/// A file the game copy check did not accept (from tools/game_sources.py check_sources).
public struct GameProblem: Decodable, Equatable {
    public enum Found: Equatable {
        case missing
        case file(FileDigest)
        case text(String)
    }

    public let path: String
    public let found: Found
    public let accepted: [AcceptedFile]

    enum CodingKeys: String, CodingKey { case path, found, accepted }

    public init(path: String, found: Found, accepted: [AcceptedFile]) {
        self.path = path
        self.found = found
        self.accepted = accepted
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        path = try container.decode(String.self, forKey: .path)
        accepted = try container.decode([AcceptedFile].self, forKey: .accepted)
        if let digest = try? container.decode(FileDigest.self, forKey: .found) {
            found = .file(digest)
        } else {
            let text = try container.decode(String.self, forKey: .found)
            found = text == "missing" ? .missing : .text(text)
        }
    }

    public var plainText: String {
        let what: String
        switch found {
        case .missing: what = "missing"
        case let .file(digest): what = "found \(digest.size) bytes, SHA-256 \(digest.sha256)"
        case let .text(text): what = text
        }
        let accepts = accepted.map { "\($0.size) bytes, SHA-256 \($0.sha256) (\($0.kind))" }
        return "- \(path): \(what); accepted: " + accepts.joined(separator: " or ")
    }
}

/// The result of checking a game copy.
public struct GameReport: Decodable, Equatable {
    public struct Discs: Decodable, Equatable {
        public let found: [Int]
        public let missing: [Int]
    }

    public let ok: Bool
    public let kind: String
    public let version: String?
    public let checked: Int
    public let failed: Int
    public let problems: [GameProblem]
    public let discs: Discs?
    public let message: String

    /// The text behind Copy details: the message and every detailed problem.
    public var plainText: String {
        var lines = [message]
        if !problems.isEmpty {
            lines.append("\(failed) of \(checked) checked files are missing or different. The first \(problems.count):")
            lines += problems.map(\.plainText)
        }
        if let discs = discs {
            lines.append("Discs found: \(discs.found.map { String($0 + 1) }.joined(separator: ", ")); "
                + "missing: \(discs.missing.map { String($0 + 1) }.joined(separator: ", "))")
        }
        return lines.joined(separator: "\n")
    }
}

/// What NFSMW Builder accepts, from `builder_cli accepted-copies`. Sizes are exact byte counts.
public struct AcceptedCopies: Decodable, Equatable {
    public struct DiscArchive: Decodable, Equatable {
        public let disc: Int
        public let archive: String
        public let size: Int64
        public let sha256: String
    }

    public struct Executable: Decodable, Equatable {
        public let kind: String
        public let label: String
        public let size: Int64
        public let sha256: String
    }

    public struct Folder: Decodable, Equatable {
        public let requiredFiles: Int
        public let totalOriginal: Int64
        public let totalOfficial: Int64
        public let executables: [Executable]
    }

    public let release: String
    public let notSupported: [String]
    public let discs: [DiscArchive]
    public let discsTotal: Int64
    public let folder: Folder

    public static let checksumNote = "The disc checksums are of the archive files inside each disc, "
        + "not of the whole ISO or BIN image."

    public var plainText: String {
        // Same digits as the README, whatever the Mac's region is.
        let number = NumberFormatter()
        number.locale = Locale(identifier: "en_US")
        number.numberStyle = .decimal
        let n = { (value: Int64) in number.string(from: NSNumber(value: value)) ?? String(value) }
        return ([release + ".", "Not supported: " + notSupported.joined(separator: ", ") + ".",
                 "The 4 original CDs (ISO or BIN/CUE):"]
            + discs.map { "- Disc \($0.disc), \($0.archive): \(n($0.size)) bytes, SHA-256 \($0.sha256)" }
            + ["  Together \(n(discsTotal)) bytes. " + Self.checksumNote,
               "An installed game folder: \(n(Int64(folder.requiredFiles))) required files, "
                   + "\(n(folder.totalOriginal)) bytes as installed from the discs, "
                   + "or \(n(folder.totalOfficial)) bytes with the official 1.3 files.",
               "speed.exe, one of:"]
            + folder.executables.map { "- \($0.label): \(n($0.size)) bytes, SHA-256 \($0.sha256)" })
            .joined(separator: "\n")
    }
}

/// Download cache state, from `builder_cli downloads status`.
public struct DownloadsStatus: Decodable, Equatable {
    public let downloads: [String: String]
    public let partialBytes: [String: Int64]
    public let totalBytes: Int64
    public let remainingBytes: Int64

    public var isReady: Bool { downloads.values.allSatisfy { $0 == "ready" } }
    public var cachedBytes: Int64 { totalBytes - remainingBytes }
}

let reportDecoder: JSONDecoder = {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return decoder
}()
