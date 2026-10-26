import XCTest
@testable import RescueSwarmCore

final class CoreTests: XCTestCase {
    func testFragmentedPythonFrame() throws {
        let url = Bundle.module.url(forResource: "python-task", withExtension: "bin", subdirectory: "Fixtures")!
        let bytes = try Data(contentsOf: url)
        var decoder = FrameDecoder()
        var frames: [Frame] = []
        for byte in bytes { frames += try decoder.append(Data([byte])) }
        XCTAssertEqual(frames.count, 1)
        XCTAssertEqual(frames[0].message.task_id, 0)
        XCTAssertEqual(frames[0].message.image_id, "fixture.ppm")
        XCTAssertEqual(frames[0].payload, Data("P6\n2 2\n255\n".utf8) + Data(repeating: 80, count: 12))
        XCTAssertFalse(decoder.hasIncompleteFrame)
    }
    func testCoalescedFramesAndRoundTrip() throws {
        var hello = Message(type: "hello"); hello.version = 1; hello.worker_id = "phone"
        let encoded = try Wire.encode(Frame(hello))
        var decoder = FrameDecoder()
        let frames = try decoder.append(encoded + encoded)
        XCTAssertEqual(frames.count, 2)
        XCTAssertEqual(frames[1].message.worker_id, "phone")
    }
    func testInvalidHeaderAndPayload() throws {
        var decoder = FrameDecoder()
        XCTAssertThrowsError(try decoder.append(Data([0, 1, 0, 1])))
        var invalid = Message(type: "task"); invalid.payload_bytes = -1
        let header = try JSONEncoder().encode(invalid)
        let n = UInt32(header.count)
        var packet = Data([UInt8(n >> 24), UInt8((n >> 16) & 255), UInt8((n >> 8) & 255), UInt8(n & 255)])
        packet.append(header)
        var other = FrameDecoder()
        XCTAssertThrowsError(try other.append(packet))
    }
    func testIncompleteFrameRetained() throws {
        var decoder = FrameDecoder()
        XCTAssertTrue(try decoder.append(Data([0, 0])).isEmpty)
        XCTAssertTrue(decoder.hasIncompleteFrame)
    }
    private func result(_ a: TaskLedger.Assignment) -> Message {
        var m = Message(type: "result")
        m.task_id = a.task; m.attempt_id = a.attempt; m.image_id = "image"
        m.status = "success"; m.processing_ms = 10; m.detections = []
        return m
    }
    func testRetryRejectsLateAndDuplicateResults() throws {
        var ledger = TaskLedger(count: 1)
        let first = ledger.assign(to: "a")!
        XCTAssertNil(ledger.assign(to: "a"))
        ledger.disconnect("a")
        let second = ledger.assign(to: "b")!
        XCTAssertEqual(second.attempt, 2)
        XCTAssertFalse(try ledger.accept(result(first), from: "b", imageID: "image"))
        XCTAssertTrue(try ledger.accept(result(second), from: "b", imageID: "image"))
        XCTAssertFalse(try ledger.accept(result(second), from: "b", imageID: "image"))
        XCTAssertTrue(ledger.finished)
        XCTAssertEqual(ledger.completed.count, 1)
    }
    func testAttemptLimitAndInvalidResult() throws {
        var ledger = TaskLedger(count: 1, maxAttempts: 1)
        let a = ledger.assign(to: "a")!
        var bad = result(a); bad.processing_ms = -1
        XCTAssertThrowsError(try ledger.accept(bad, from: "a", imageID: "image"))
        XCTAssertFalse(ledger.finished)
        ledger.disconnect("a")
        XCTAssertTrue(ledger.finished)
        XCTAssertEqual(ledger.failed, [0])
    }
    func testNextAvailableAndEmptyLedger() {
        var ledger = TaskLedger(count: 2)
        XCTAssertEqual(ledger.assign(to: "a")?.task, 0)
        XCTAssertEqual(ledger.assign(to: "b")?.task, 1)
        XCTAssertNil(ledger.assign(to: "c"))
        XCTAssertTrue(TaskLedger(count: 0).finished)
    }
}
