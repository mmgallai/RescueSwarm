import Foundation
import XCTest
@testable import RescueSwarmCore

final class DetectionWorkerTests: XCTestCase {
    static var detector: PersonDetector?

    func loadDetector() async throws -> PersonDetector {
        if let detector = Self.detector { return detector }
        let detector = try await PersonDetector.load(from: bundledModelURL, computeUnits: .cpuOnly)
        Self.detector = detector
        return detector
    }

    func testSuccessResultCarriesSizeDetectorAndConfig() async throws {
        let result = DetectionWorker.process(jpeg(width: 640, height: 480), task: 3, attempt: 2,
                                             imageID: "a.jpg", detector: try await loadDetector())
        XCTAssertEqual(result.type, "result")
        XCTAssertEqual([result.task_id, result.attempt_id], [3, 2])
        XCTAssertEqual(result.image_id, "a.jpg")
        XCTAssertEqual(result.status, "success")
        XCTAssertEqual(result.detections, [])
        XCTAssertEqual(result.image_size, ImageSize(width: 640, height: 480))
        XCTAssertEqual(result.synthetic, false)
        XCTAssertEqual(result.detector, "yolo26n")
        XCTAssertEqual(result.detector_config, DetectorConfig(model: "yolo26n", imgsz: 1280, conf: 0.25, runtime: "coreml"))
        XCTAssertNil(result.error)
        XCTAssertGreaterThan(result.processing_ms ?? 0, 0)
    }

    func testUndecodableImageBecomesFailureResult() async throws {
        let result = DetectionWorker.process(Data("not an image".utf8), task: 0, attempt: 1,
                                             imageID: "bad.jpg", detector: try await loadDetector())
        XCTAssertEqual(result.status, "failure")
        XCTAssertEqual(result.detections, [])
        XCTAssertEqual(result.error, "undecodableImage")
        XCTAssertNil(result.image_size)
    }

    func testCoordinatorFixtureImageIsProcessed() async throws {
        // The coordinator's default 2x2 PPM test image must not turn into a failure.
        let fixture = Data("P6\n2 2\n255\n".utf8) + Data(repeating: 80, count: 12)
        let result = DetectionWorker.process(fixture, task: 0, attempt: 1, imageID: "fixture.ppm",
                                             detector: try await loadDetector())
        XCTAssertEqual(result.status, "success")
        XCTAssertEqual(result.image_size, ImageSize(width: 2, height: 2))
    }

    func testResultIsAcceptedByTheCoordinatorLedger() async throws {
        var ledger = TaskLedger(count: 1, roster: ["phone"])
        let assignment = try XCTUnwrap(ledger.assign(to: "phone", connected: ["phone"]))
        let result = DetectionWorker.process(jpeg(width: 64, height: 64), task: assignment.task,
                                             attempt: assignment.attempt, imageID: "a.jpg",
                                             detector: try await loadDetector())
        // Round-trip through the wire format, as the coordinator receives it.
        let frames = try {
            var decoder = FrameDecoder()
            return try decoder.append(Wire.encode(Frame(result)))
        }()
        XCTAssertTrue(try ledger.accept(frames[0].message, from: "phone", imageID: "a.jpg"))
    }
}

final class MessageFieldTests: XCTestCase {
    func testNewFieldsAreOmittedWhenEmpty() throws {
        let json = String(decoding: try JSONEncoder().encode(Message(type: "heartbeat")), as: UTF8.self)
        XCTAssertFalse(json.contains("image_size") || json.contains("error") || json.contains("detector_config"))
    }

    func testPythonWorkerResultDecodes() throws {
        // As sent by rescueswarm/tcp_worker.py: detector_config without "runtime".
        let json = """
            {"type": "result", "task_id": 1, "attempt_id": 1, "image_id": "x.jpg", "status": "success",
             "processing_ms": 112.5, "detector": "yolo26n", "synthetic": false, "payload_bytes": 0,
             "detections": [{"label": "person", "confidence": 0.8, "box_xyxy": [1, 2, 30, 40]}],
             "image_size": {"width": 5472, "height": 3648},
             "detector_config": {"model": "yolo26n", "imgsz": 1280, "conf": 0.25}}
            """
        let message = try JSONDecoder().decode(Message.self, from: Data(json.utf8))
        XCTAssertEqual(message.image_size, ImageSize(width: 5472, height: 3648))
        XCTAssertEqual(message.detector_config, DetectorConfig(model: "yolo26n", imgsz: 1280, conf: 0.25))
        XCTAssertEqual(message.detections?.count, 1)
    }
}
