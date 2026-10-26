import XCTest
@testable import RescueSwarmCore

final class ReportTests: XCTestCase {
    private func store() throws -> ReportStore {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return ReportStore(directory: directory)
    }
    private func saved(task: Int = 0, image: String = "a") -> SavedResult {
        var m = Message(type: "result")
        m.task_id = task; m.attempt_id = 1; m.image_id = image
        m.status = "success"; m.processing_ms = 10; m.detections = []
        m.synthetic = true; m.detector = "mock"
        return SavedResult(workerID: "phone", receivedSeconds: 0.2, result: m)
    }
    func testSaveReloadPreservesIdentityAndProvenance() throws {
        let store = try store()
        var report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        try report.append(saved())
        try store.save(report)
        let loaded = try store.load(store.url(for: report.id))
        XCTAssertEqual(loaded.id, report.id)
        XCTAssertEqual(loaded.results.count, 1)
        XCTAssertEqual(loaded.results[0].result.synthetic, true)
        XCTAssertEqual(loaded.first_result_s, 0.2)
        XCTAssertEqual(loaded.tasks_per_worker, ["phone": 1])
    }
    func testDuplicateDoesNotChangeMetrics() throws {
        var report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        try report.append(saved())
        XCTAssertThrowsError(try report.append(saved()))
        XCTAssertEqual(report.results.count, 1)
        XCTAssertEqual(report.tasks_per_worker["phone"], 1)
    }
    func testWrongImageAndOutOfRangeRejected() {
        var report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        XCTAssertThrowsError(try report.append(saved(image: "wrong")))
        XCTAssertThrowsError(try report.append(saved(task: 1)))
        XCTAssertTrue(report.results.isEmpty)
    }
    func testReplacingCheckpointUsesSameFile() throws {
        let store = try store()
        var report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        try store.save(report)
        try report.append(saved())
        report.state = "finished"
        try store.save(report)
        XCTAssertEqual(try store.files().count, 1)
        XCTAssertEqual(try store.load(store.url(for: report.id)).state, "finished")
    }
    func testEncodingFailureKeepsPreviousCheckpoint() throws {
        let store = try store()
        var report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        try store.save(report)
        report.elapsed_s = .nan
        XCTAssertThrowsError(try store.save(report))
        XCTAssertEqual(try store.load(store.url(for: report.id)).elapsed_s, 0)
    }
    func testUnfinishedAndCorruptReportsAreNotSuccess() throws {
        let store = try store()
        let report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        try store.save(report)
        XCTAssertEqual(try store.load(store.url(for: report.id)).state, "running")
        try Data("broken".utf8).write(to: store.url(for: report.id))
        XCTAssertThrowsError(try store.load(store.url(for: report.id)))
    }
}
