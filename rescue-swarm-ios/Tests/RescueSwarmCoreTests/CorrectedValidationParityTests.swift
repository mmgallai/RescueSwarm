import Foundation
import CoreVideo
import XCTest
@testable import RescueSwarmCore

/// Export real app detections and its exact input pixels for a paired Python audit.
final class CorrectedValidationParityTests: XCTestCase {
    func testExportCorrectedValidationDetections() async throws {
        guard let path = ProcessInfo.processInfo.environment["PARITY_ROOT"] else {
            throw XCTSkip("Run the Corrected validation parity workflow to provision the frozen sample")
        }
        let root = URL(fileURLWithPath: path)
        let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("manifest.json"))) as! [String: Any]
        let images = manifest["images"] as! [[String: Any]]
        XCTAssertEqual(images.count, 32)
        let detector = try await PersonDetector.load(from: bundledModelURL, computeUnits: .all)
        XCTAssertEqual(detector.inputSize, 1280)
        XCTAssertEqual(PersonDetector.iouThreshold, 0.7)
        var records: [[String: Any]] = []
        for row in images {
            let id = row["id"] as! String
            let data = try Data(contentsOf: root.appendingPathComponent(row["path"] as! String))
            let detected = try detector.detect(imageData: data, confidenceThreshold: 0.25)
            XCTAssertEqual(detected.imageWidth, row["width"] as? Int)
            XCTAssertEqual(detected.imageHeight, row["height"] as? Int)
            let prepared = try ImagePreparation.prepare(data, size: 1280)
            try rgbPPM(prepared.pixelBuffer).write(to: root.appendingPathComponent(id + "-swift.ppm"))
            records.append(["id": id, "width": detected.imageWidth, "height": detected.imageHeight,
                "elapsed_ms": detected.elapsedMs,
                "detections": detected.detections.map { ["box": $0.box_xyxy, "confidence": $0.confidence] as [String: Any] }])
            print("PARITY_SWIFT \(id): \(detected.detections.count) detections")
        }
        try JSONSerialization.data(withJSONObject: ["images": records], options: [.prettyPrinted, .sortedKeys])
            .write(to: root.appendingPathComponent("swift-results.json"))
    }

    private func rgbPPM(_ buffer: CVPixelBuffer) throws -> Data {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        let source = try XCTUnwrap(CVPixelBufferGetBaseAddress(buffer)).assumingMemoryBound(to: UInt8.self)
        var rgb = [UInt8](repeating: 0, count: width * height * 3)
        for y in 0..<height {
            for x in 0..<width {
                let src = y * stride + x * 4, dst = (y * width + x) * 3
                rgb[dst] = source[src + 2]; rgb[dst + 1] = source[src + 1]; rgb[dst + 2] = source[src]
            }
        }
        return Data("P6\n\(width) \(height)\n255\n".utf8) + Data(rgb)
    }
}
