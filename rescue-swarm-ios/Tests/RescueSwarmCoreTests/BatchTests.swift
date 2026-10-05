import XCTest
@testable import RescueSwarmCore

final class BatchTests: XCTestCase {
    private func result(_ a: TaskLedger.Assignment) -> Message {
        var m = Message(type: "result")
        m.task_id = a.task; m.attempt_id = a.attempt; m.image_id = "image"
        m.status = "success"; m.processing_ms = 1; m.detections = []
        return m
    }
    func testRoundRobinIgnoresConnectionOrder() throws {
        var ledger = TaskLedger(count: 4, policy: .roundRobin, roster: ["b", "a"])
        let b = ledger.assign(to: "b", connected: ["a", "b"])!
        let a = ledger.assign(to: "a", connected: ["a", "b"])!
        XCTAssertEqual(b.task, 1); XCTAssertEqual(a.task, 0)
        XCTAssertTrue(try ledger.accept(result(b), from: "b", imageID: "image"))
        XCTAssertEqual(ledger.assign(to: "b", connected: ["a", "b"])?.task, 3)
    }
    func testRoundRobinOrphansAndRetries() {
        var ledger = TaskLedger(count: 3, policy: .roundRobin, roster: ["a", "b"])
        let first = ledger.assign(to: "a", connected: ["a", "b"])!
        ledger.disconnect("a")
        let retry = ledger.assign(to: "b", connected: ["b"])!
        XCTAssertEqual(first.task, retry.task); XCTAssertEqual(retry.attempt, 2)
        var orphan = TaskLedger(count: 2, policy: .roundRobin, roster: ["a", "b"])
        XCTAssertEqual(orphan.assign(to: "b", connected: ["b"])?.task, 0)
    }
    func testLateJoinerCannotStealHealthyHome() {
        var ledger = TaskLedger(count: 2, policy: .roundRobin, roster: ["a", "b"])
        XCTAssertNil(ledger.assign(to: "c", connected: ["a", "b", "c"]))
    }
    func testSingleOnlyOneInflight() throws {
        var ledger = TaskLedger(count: 2, policy: .single)
        let first = ledger.assign(to: "a")!
        XCTAssertNil(ledger.assign(to: "b"))
        XCTAssertTrue(try ledger.accept(result(first), from: "a", imageID: "image"))
        XCTAssertEqual(ledger.assign(to: "a")?.task, 1)
    }
    func testNextAvailableGivesFastWorkerMoreWork() throws {
        var ledger = TaskLedger(count: 4)
        _ = ledger.assign(to: "slow")
        for expected in 1...3 {
            let a = ledger.assign(to: "fast")!
            XCTAssertEqual(a.task, expected)
            XCTAssertTrue(try ledger.accept(result(a), from: "fast", imageID: "image"))
        }
        XCTAssertEqual(ledger.completed.count, 3)
        XCTAssertEqual(ledger.active["slow"]?.task, 0)
    }
    func testWrongImageCannotCompleteTask() throws {
        var ledger = TaskLedger(count: 2)
        let a = ledger.assign(to: "a")!
        XCTAssertThrowsError(try ledger.accept(result(a), from: "a", imageID: "different"))
        XCTAssertTrue(ledger.completed.isEmpty)
    }
    private func temporaryRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }
    func testCopyIsIndependentAndDuplicateNamesAreUnique() throws {
        let root = try temporaryRoot()
        let source = root.appendingPathComponent("photo.png")
        try Data([1, 2, 3]).write(to: source)
        let batch = try ImageBatch.copy([source, source], into: root)
        try FileManager.default.removeItem(at: source)
        XCTAssertEqual(batch.items.count, 2)
        XCTAssertNotEqual(batch.items[0].imageID, batch.items[1].imageID)
        XCTAssertEqual(try batch.read(1), Data([1, 2, 3]))
    }
    func testFailedImportRollsBackTemporaryBatch() throws {
        let root = try temporaryRoot()
        let source = root.appendingPathComponent("valid.png")
        try Data([1]).write(to: source)
        XCTAssertThrowsError(try ImageBatch.copy([source, root.appendingPathComponent("missing")], into: root))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), ["valid.png"])
    }
    func testRejectEmptySelectionAndModifiedFile() throws {
        let root = try temporaryRoot()
        XCTAssertThrowsError(try ImageBatch.copy([], into: root))
        let source = root.appendingPathComponent("a.png")
        try Data([1]).write(to: source)
        let batch = try ImageBatch.copy([source], into: root)
        try Data([1, 2]).write(to: batch.items[0].url)
        XCTAssertThrowsError(try batch.read(0))
        XCTAssertThrowsError(try batch.read(1))
    }
    func testRejectEmptyAndOversizeFiles() throws {
        let root = try temporaryRoot()
        let source = root.appendingPathComponent("a.png")
        try Data().write(to: source)
        XCTAssertThrowsError(try ImageBatch.copy([source], into: root))
        let handle = try FileHandle(forWritingTo: source)
        try handle.truncate(atOffset: UInt64(Wire.maxPayload + 1))
        try handle.close()
        XCTAssertThrowsError(try ImageBatch.copy([source], into: root))
    }
}
