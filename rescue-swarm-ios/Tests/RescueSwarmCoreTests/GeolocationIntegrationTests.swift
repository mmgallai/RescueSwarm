import XCTest
@testable import RescueSwarmCore

final class GeolocationIntegrationTests: XCTestCase {
    private func row(hash: String = String(repeating: "a", count: 64), pitch: Double = -90) -> [String: Any] {
        ["image_sha256": hash, "width": 100, "height": 100, "captured_at": "2026-11-21T12:00:00Z",
         "latitude": 42.0, "longitude": -76.0, "altitude_agl_m": 50.0,
         "horizontal_fov_deg": 60.0, "vertical_fov_deg": 60.0, "camera_heading_deg": 0.0,
         "camera_pitch_deg": pitch, "camera_roll_deg": 0.0]
    }
    private func manifest(_ rows: [[String: Any]]) throws -> TelemetryManifest {
        try TelemetryManifest.load(JSONSerialization.data(withJSONObject: ["schema_version": 1, "images": rows]))
    }
    private func result(attempt: Int = 1) -> Message {
        var m = Message(type: "result")
        m.task_id = 0; m.attempt_id = attempt; m.image_id = "0000-image.jpg"
        m.status = "success"; m.processing_ms = 10; m.image_size = ImageSize(width: 100, height: 100)
        m.detections = [Detection(label: "person", confidence: 0.9, box_xyxy: [40, 30, 60, 50]),
                        Detection(label: "person", confidence: 0.8, box_xyxy: [60, 30, 80, 50])]
        return m
    }
    func testAcceptedWorkerResultProducesTwoStableLocatedSightingsAndSurvivesReload() throws {
        let m = result()
        var ledger = TaskLedger(count: 1)
        XCTAssertNotNil(ledger.assign(to: "phone"))
        XCTAssertTrue(try ledger.accept(m, from: "phone", imageID: m.image_id!))
        var report = SessionReport(policy: "single", imageIDs: [m.image_id!], expectedWorkers: 1)
        report.telemetry = [m.image_id!: try manifest([row()]).images[0]]
        let saved = SavedResult(workerID: "phone", receivedSeconds: 1, result: m)
        try report.append(saved)
        let sightings = try XCTUnwrap(report.sightings)
        XCTAssertEqual(sightings.count, 2)
        XCTAssertEqual(try XCTUnwrap(sightings[0].latitude), 42, accuracy: 0.000001)
        XCTAssertEqual(try XCTUnwrap(sightings[0].longitude), -76, accuracy: 0.000001)
        XCTAssertGreaterThan(try XCTUnwrap(sightings[1].longitude), -76)
        XCTAssertNotEqual(sightings[0].id, sightings[1].id)
        XCTAssertTrue(sightings[0].cot_xml?.contains("2026-11-21T12:00:00Z") == true)
        XCTAssertThrowsError(try report.append(saved))
        XCTAssertEqual(report.sightings?.count, 2)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        let store = ReportStore(directory: dir)
        try store.save(report)
        let restored = try store.load(store.url(for: report.id))
        XCTAssertEqual(restored.sightings?.map(\.id), sightings.map(\.id))
        XCTAssertEqual(restored.telemetry?.count, 1)
    }
    func testRetryRejectsOldResultAndCreatesOneSetOfSightings() throws {
        var ledger = TaskLedger(count: 1)
        _ = ledger.assign(to: "first")
        ledger.disconnect("first")
        _ = ledger.assign(to: "second")
        XCTAssertFalse(try ledger.accept(result(), from: "second", imageID: "0000-image.jpg"))
        XCTAssertTrue(try ledger.accept(result(attempt: 2), from: "second", imageID: "0000-image.jpg"))
        let telemetry = try manifest([row()]).images[0]
        let id = UUID()
        XCTAssertEqual(Sighting.locate(result(), runID: id, telemetry: telemetry).map(\.id),
                       Sighting.locate(result(attempt: 2), runID: id, telemetry: telemetry).map(\.id))
    }
    func testMissingTelemetryAndTiltAreExplicitUnlocatedDetections() throws {
        let missing = Sighting.locate(result(), runID: UUID(), telemetry: nil)
        XCTAssertEqual(missing.count, 2)
        XCTAssertTrue(missing.allSatisfy { $0.cot_xml == nil && $0.latitude == nil && $0.issue != nil })
        let tilted = try manifest([row(pitch: -60)]).images[0]
        XCTAssertTrue(Sighting.locate(result(), runID: UUID(), telemetry: tilted).allSatisfy { $0.cot_xml == nil && $0.issue != nil })
    }
    func testImageSizeMismatchAndOutOfBoundsBoxesCannotProduceLocations() throws {
        let telemetry = try manifest([row()]).images[0]
        var m = result()
        m.image_size = ImageSize(width: 200, height: 100)
        XCTAssertTrue(Sighting.locate(m, runID: UUID(), telemetry: telemetry).allSatisfy { $0.cot_xml == nil })
        m = result()
        m.detections![0].box_xyxy = [10, 10, 200, 40]
        let sightings = Sighting.locate(m, runID: UUID(), telemetry: telemetry)
        XCTAssertNil(sightings[0].cot_xml)
        XCTAssertNotNil(sightings[1].cot_xml)
    }
    func testSyntheticResultCannotCreateLocatedSighting() throws {
        var m = result(); m.synthetic = true
        XCTAssertTrue(Sighting.locate(m, runID: UUID(), telemetry: try manifest([row()]).images[0]).allSatisfy { $0.cot_xml == nil })
    }
    func testManifestRejectsDuplicateHashAndInvalidMetadata() throws {
        XCTAssertThrowsError(try manifest([row(), row()]))
        XCTAssertThrowsError(try manifest([row(hash: "bad")]))
        var bad = row(); bad["altitude_agl_m"] = -5
        XCTAssertThrowsError(try manifest([bad]))
        bad = row(); bad.removeValue(forKey: "camera_pitch_deg")
        XCTAssertThrowsError(try manifest([bad]))
    }
    func testMatchingUsesImageBytesAcrossImportRenaming() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("image.jpg")
        try Data([1, 2, 3]).write(to: source)
        let batch = try ImageBatch.copy([source], into: root)
        let matching = try manifest([row(hash: batch.items[0].sha256)])
        XCTAssertEqual(matching.match(batch).keys.sorted(), ["0000-image.jpg"])
        XCTAssertTrue(try manifest([row()]).match(batch).isEmpty)
    }
    func testLegacyReportWithoutNewFieldsStillLoads() throws {
        let report = SessionReport(policy: "single", imageIDs: ["a"], expectedWorkers: 1)
        let bytes = try JSONEncoder().encode(report)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
        object.removeValue(forKey: "telemetry"); object.removeValue(forKey: "sightings")
        let loaded = try JSONDecoder().decode(SessionReport.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertEqual(loaded.id, report.id)
        XCTAssertNil(loaded.sightings)
    }
}
