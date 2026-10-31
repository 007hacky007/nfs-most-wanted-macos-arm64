import Foundation

public enum PipelineEvent: Equatable {
    case step(id: String, title: String)
    case done(URL)
    case error(message: String, log: String?)
    case game(version: String, kind: String)
    case gameRejected(message: String, report: GameReport)
    case download(key: String, received: Int64, total: Int64)
    case downloads(DownloadsStatus)
    case downloadsReady
    case accepted(AcceptedCopies)
    case log(String)
}

public let eventPrefix = "NFSMW-EVENT "

/// One output line of a pipeline command. Lines without the prefix, malformed JSON and
/// payloads of an unknown shape are plain log text.
public func parsePipelineLine(_ line: String) -> PipelineEvent {
    guard line.hasPrefix(eventPrefix),
          let data = String(line.dropFirst(eventPrefix.count)).data(using: .utf8),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    else { return .log(line) }

    func decode<T: Decodable>(_ type: T.Type, _ value: Any?) -> T? {
        guard let value = value, JSONSerialization.isValidJSONObject(value),
              let json = try? JSONSerialization.data(withJSONObject: value) else { return nil }
        return try? reportDecoder.decode(type, from: json)
    }
    func integer(_ value: Any?) -> Int64? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        return number.int64Value
    }

    if let id = obj["step"] as? String, let title = obj["title"] as? String {
        return .step(id: id, title: title)
    }
    if let path = obj["done"] as? String { return .done(URL(fileURLWithPath: path)) }
    if let message = obj["error"] as? String {
        if obj["report"] != nil {
            guard let report = decode(GameReport.self, obj["report"]) else { return .log(line) }
            return .gameRejected(message: message, report: report)
        }
        return .error(message: message, log: obj["log"] as? String)
    }
    if obj["game"] as? String == "ok", let version = obj["version"] as? String, let kind = obj["kind"] as? String {
        return .game(version: version, kind: kind)
    }
    if let key = obj["download"] as? String, let received = integer(obj["received"]), let total = integer(obj["total"]) {
        return .download(key: key, received: received, total: total)
    }
    if obj["downloads"] as? String == "ready" { return .downloadsReady }
    if obj["downloads"] is [String: Any], let status = decode(DownloadsStatus.self, obj) {
        return .downloads(status)
    }
    if let accepted = decode(AcceptedCopies.self, obj["accepted"]) { return .accepted(accepted) }
    return .log(line)
}
