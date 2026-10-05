import Foundation

// Value type owned exclusively by the app's main actor in this first milestone.
// No inference or blocking network IO runs inside this ledger.
public struct TaskLedger {
    public enum Policy: String, CaseIterable { case single, roundRobin, nextAvailable }
    public struct Assignment: Equatable {
        public let task: Int
        public let attempt: Int
        public let worker: String
    }
    public private(set) var pending: [Int]
    public private(set) var active: [String: Assignment] = [:]
    public private(set) var completed: Set<Int> = []
    public private(set) var failed: Set<Int> = []
    private var attempts: [Int: Int] = [:]
    private let count: Int
    private let maxAttempts: Int
    private let policy: Policy
    private let roster: [String]
    public init(count: Int, maxAttempts: Int = 3, policy: Policy = .nextAvailable, roster: [String] = []) {
        precondition(count >= 0 && maxAttempts > 0)
        precondition(policy != .roundRobin || !roster.isEmpty)
        self.count = count
        self.maxAttempts = maxAttempts
        self.pending = Array(0..<count)
        self.policy = policy
        self.roster = Array(Set(roster)).sorted()
    }
    public var finished: Bool { completed.count + failed.count == count }
    public mutating func assign(to worker: String, connected: Set<String>? = nil) -> Assignment? {
        guard active[worker] == nil, !pending.isEmpty else { return nil }
        if policy == .single && !active.isEmpty { return nil }
        let index = pending.firstIndex { task in
            guard policy == .roundRobin else { return true }
            let home = roster[task % roster.count]
            return home == worker || !(connected ?? Set(roster)).contains(home) || (attempts[task] ?? 0) > 0
        }
        guard let index else { return nil }
        let task = pending.remove(at: index)
        let attempt = (attempts[task] ?? 0) + 1
        attempts[task] = attempt
        let assignment = Assignment(task: task, attempt: attempt, worker: worker)
        active[worker] = assignment
        return assignment
    }
    public mutating func accept(_ message: Message, from worker: String, imageID: String) throws -> Bool {
        guard let assignment = active[worker], message.task_id == assignment.task,
              message.attempt_id == assignment.attempt else { return false }
        guard message.type == "result", message.payload_bytes == 0,
              message.image_id == imageID, message.status == "success",
              let duration = message.processing_ms, duration.isFinite, duration >= 0,
              let detections = message.detections else { throw WireError.invalidResult }
        for d in detections {
            let b = d.box_xyxy
            guard d.label == "person", d.confidence.isFinite, (0...1).contains(d.confidence),
                  b.count == 4, b.allSatisfy({ $0.isFinite }),
                  b[0] >= 0, b[1] >= 0, b[2] > b[0], b[3] > b[1] else { throw WireError.invalidResult }
        }
        completed.insert(assignment.task)
        active.removeValue(forKey: worker)
        return true
    }
    public mutating func disconnect(_ worker: String) {
        guard let assignment = active.removeValue(forKey: worker) else { return }
        if assignment.attempt < maxAttempts { pending.insert(assignment.task, at: 0) }
        else { failed.insert(assignment.task) }
    }
}
