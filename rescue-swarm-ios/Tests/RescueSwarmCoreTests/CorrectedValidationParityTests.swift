import Foundation
import CoreVideo
import CoreML
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
        let settings = manifest["settings"] as! [String: Any]
        let size = settings["imgsz"] as! Int
        let cutoff = settings["conf"] as! Double
        let inferenceCut = settings["inference_conf"] as? Double ?? cutoff
        let nmsCut = settings["iou"] as! Double
        XCTAssertEqual(images.count, manifest["crop_fixture"] as? Bool == true ? 512 : 32)
        let modelURL = ProcessInfo.processInfo.environment["PARITY_MODEL"].map { URL(fileURLWithPath: $0) } ?? bundledModelURL
        let detector = try await PersonDetector.load(from: modelURL, computeUnits: .all)
        XCTAssertEqual(detector.model.modelDescription.inputDescriptionsByName["image"]?.imageConstraint?.pixelsWide, size)
        XCTAssertEqual(PersonDetector.iouThreshold, 0.7)
        var records: [[String: Any]] = []
        for row in images {
            let id = row["id"] as! String
            let data = try Data(contentsOf: root.appendingPathComponent(row["path"] as! String))
            let prepared = try ImagePreparation.prepare(data, size: size)
            let input = try MLDictionaryFeatureProvider(dictionary: [
                "image": MLFeatureValue(pixelBuffer: prepared.pixelBuffer),
                "iouThreshold": MLFeatureValue(double: nmsCut),
                "confidenceThreshold": MLFeatureValue(double: inferenceCut)])
            let began = Date()
            let output = try detector.model.prediction(from: input)
            let decoded = OutputDecoding.decode(OutputDecoding.rows(from: ModelOutput(
                coordinates: try XCTUnwrap(output.featureValue(for: "coordinates")?.multiArrayValue),
                confidence: try XCTUnwrap(output.featureValue(for: "confidence")?.multiArrayValue))),
                letterbox: prepared.letterbox, originalWidth: prepared.originalWidth,
                originalHeight: prepared.originalHeight, confidenceThreshold: cutoff)
            let detected = DetectorResult(detections: decoded, imageWidth: prepared.originalWidth,
                imageHeight: prepared.originalHeight, elapsedMs: Date().timeIntervalSince(began) * 1000)
            XCTAssertEqual(detected.imageWidth, row["width"] as? Int)
            XCTAssertEqual(detected.imageHeight, row["height"] as? Int)
            try rgbPPM(prepared.pixelBuffer).write(to: root.appendingPathComponent(id + "-swift.ppm"))
            records.append(["id": id, "width": detected.imageWidth, "height": detected.imageHeight,
                "elapsed_ms": detected.elapsedMs,
                "detections": detected.detections.map { ["box": $0.box_xyxy, "confidence": $0.confidence] as [String: Any] }])
            print("PARITY_SWIFT \(id): \(detected.detections.count) detections")
        }
        if manifest["crop_fixture"] as? Bool == true {
            var groups: [String: [[String: Any]]] = [:]
            for (row, record) in zip(images, records) {
                let source = row["source_id"] as! String
                let rect = row["rect"] as! [Int]
                for detection in record["detections"] as! [[String: Any]] {
                    let b = detection["box"] as! [Double]
                    groups[source, default: []].append(["box": [b[0]+Double(rect[0]), b[1]+Double(rect[1]),
                        b[2]+Double(rect[0]), b[3]+Double(rect[1])], "confidence": detection["confidence"]!])
                }
                if groups[source] == nil { groups[source] = [] }
            }
            var merged: [[String: Any]] = []
            for id in groups.keys.sorted() {
                let sorted = groups[id]!.enumerated().sorted {
                    let a = $0.element["confidence"] as! Double, b = $1.element["confidence"] as! Double
                    return a == b ? $0.offset < $1.offset : a > b
                }.map { $0.element }
                var kept: [[String: Any]] = []
                for d in sorted {
                    if kept.allSatisfy({ overlap(d["box"] as! [Double], $0["box"] as! [Double]) <= 0.5 }) { kept.append(d) }
                }
                merged.append(["id": id, "detections": kept])
            }
            try JSONSerialization.data(withJSONObject: ["images": merged], options: [.prettyPrinted, .sortedKeys])
                .write(to: root.appendingPathComponent("swift-merged.json"))
        }
        try JSONSerialization.data(withJSONObject: ["images": records], options: [.prettyPrinted, .sortedKeys])
            .write(to: root.appendingPathComponent("swift-results.json"))
    }

    private func overlap(_ a: [Double], _ b: [Double]) -> Double {
        let intersection = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
        let union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
        return union > 0 ? intersection/union : 0
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
