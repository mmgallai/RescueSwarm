import Foundation

public struct SavedResult: Codable {
    public let worker_id: String
    public let received_s: Double
    public let result: Message
    public init(workerID: String, receivedSeconds: Double, result: Message) {
        worker_id = workerID; received_s = receivedSeconds; self.result = result
    }
}

public struct SessionReport: Codable, Identifiable {
    public let schema_version: Int
    public let id: UUID
    public let started_at: Date
    public let policy: String
    public let image_ids: [String]
    public let expected_workers: Int
    public var state = "running"
    public var stop_reason: String?
    public var elapsed_s: Double = 0
    public var batch_s: Double?
    public var assignments = 0
    public var retries = 0
    // Bytes submitted to transport, not confirmed wire delivery; includes retry payloads.
    public var image_bytes_submitted = 0
    public var failed_task_ids: [Int] = []
    public private(set) var results: [SavedResult] = []
    public private(set) var first_result_s: Double?
    public private(set) var tasks_per_worker: [String: Int] = [:]
    public init(policy: String, imageIDs: [String], expectedWorkers: Int) {
        schema_version = 1; id = UUID(); started_at = Date()
        self.policy = policy; image_ids = imageIDs; expected_workers = expectedWorkers
    }
    public mutating func append(_ saved: SavedResult) throws {
        guard let task = saved.result.task_id, image_ids.indices.contains(task),
              saved.result.image_id == image_ids[task], saved.result.status == "success",
              saved.received_s.isFinite, saved.received_s >= 0,
              !results.contains(where: { $0.result.task_id == task }) else { throw WireError.invalidResult }
        results.append(saved)
        first_result_s = results.map(\.received_s).min()
        tasks_per_worker[saved.worker_id, default: 0] += 1
    }
}

/// Atomic checkpoints. An unfinished snapshot is evidence, not a resumable queue.
public struct ReportStore {
    public let directory: URL
    public init(directory: URL) { self.directory = directory }
    public func url(for id: UUID) -> URL { directory.appendingPathComponent(id.uuidString).appendingPathExtension("json") }
    public func save(_ report: SessionReport) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(report).write(to: url(for: report.id), options: .atomic)
    }
    public func load(_ url: URL) throws -> SessionReport {
        let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .iso8601
        let value = try decoder.decode(SessionReport.self, from: Data(contentsOf: url))
        guard value.schema_version == 1 else { throw WireError.invalidHeader }
        return value
    }
    public func files() throws -> [URL] {
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }
        return try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
    }
}
