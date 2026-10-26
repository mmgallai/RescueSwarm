import Foundation
import XCTest
@testable import RescueSwarmCore

/// Checks the Swift detector against the Python reference on real SAR-DAG photos.
///
/// Fixtures/sardag-reference.json holds the boxes found by the same Core ML model with the
/// Python letterbox/decode (scripts/export_swift_fixture.py on evi/detection-worker). The
/// photos themselves are too big to commit, so the test reads them from SAR-DAG on disk and
/// is skipped when it is not there. Set SARDAG_ROOT to the dataset's drone_data folder, or keep
/// the RescueSwarm Python checkout next to this one with the dataset unpacked in data/.
final class SarDagParityTests: XCTestCase {
    struct Reference: Decodable {
        struct Box: Decodable { let box_xyxy: [Double]; let confidence: Double }
        struct Image: Decodable {
            let image_id: String
            let path: String
            let width: Int
            let height: Int
            let ground_truth: [[Double]]
            let reference: [Box]
        }
        let conf: Double
        let images: [Image]
    }

    static let confident = 0.5  // reference boxes at or above this must always be found

    static var datasetRoot: URL {
        if let root = ProcessInfo.processInfo.environment["SARDAG_ROOT"] {
            return URL(fileURLWithPath: root)
        }
        // <checkout>/rescue-swarm-ios/Tests/RescueSwarmCoreTests/this file -> sibling RescueSwarm checkout
        return URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("RescueSwarm/data/sar-dag/SAR-DAG_raycast/drone_data")
    }

    func testSwiftDetectorFindsTheSameBoxesAsThePythonReference() async throws {
        let root = Self.datasetRoot
        try XCTSkipUnless(FileManager.default.fileExists(atPath: root.path),
                          "SAR-DAG not found at \(root.path); set SARDAG_ROOT")
        let url = try XCTUnwrap(Bundle.module.url(forResource: "sardag-reference", withExtension: "json",
                                                  subdirectory: "Fixtures"))
        let reference = try JSONDecoder().decode(Reference.self, from: Data(contentsOf: url))
        let detector = try await PersonDetector.load(from: bundledModelURL)

        var referenceBoxes = 0, matched = 0, swiftOnly = 0
        var ious: [Double] = [], confidenceDiffs: [Double] = []
        var truePositives = 0, people = 0
        var totalMs = 0.0
        var missedConfident: [String] = []
        for image in reference.images {
            let data = try Data(contentsOf: root.appendingPathComponent(image.path))
            let result = try detector.detect(imageData: data, confidenceThreshold: reference.conf)
            XCTAssertEqual([result.imageWidth, result.imageHeight], [image.width, image.height], image.image_id)
            totalMs += result.elapsedMs

            // Pair each reference box with the best-overlapping Swift box.
            var unmatched = result.detections
            for box in image.reference {
                referenceBoxes += 1
                let best = unmatched.indices.max { iou($0, box) < iou($1, box) }
                if let best, iou(best, box) >= 0.5 {
                    matched += 1
                    ious.append(iou(best, box))
                    confidenceDiffs.append(abs(unmatched[best].confidence - box.confidence))
                    unmatched.remove(at: best)
                } else if box.confidence >= Self.confident {
                    missedConfident.append("\(image.image_id) (\(box.confidence))")
                }
                func iou(_ i: Int, _ b: Reference.Box) -> Double { boxIoU(unmatched[i].box_xyxy, b.box_xyxy) }
            }
            swiftOnly += unmatched.count

            people += image.ground_truth.count
            truePositives += image.ground_truth.filter { truth in
                result.detections.contains { boxIoU($0.box_xyxy, truth) >= 0.5 }
            }.count
        }

        let meanIoU = ious.reduce(0, +) / Double(max(ious.count, 1))
        let meanConfidenceDiff = confidenceDiffs.reduce(0, +) / Double(max(confidenceDiffs.count, 1))
        print("""
            SAR-DAG parity: \(matched)/\(referenceBoxes) reference boxes matched, \(swiftOnly) found only by Swift, \
            mean IoU \(String(format: "%.3f", meanIoU)), mean confidence difference \
            \(String(format: "%.3f", meanConfidenceDiff)); Swift recall \(truePositives)/\(people), \
            \(String(format: "%.0f", totalMs / Double(reference.images.count))) ms/image
            """)
        // Swift shrinks photos with ImageIO and Python with OpenCV, so pixels differ slightly and
        // borderline boxes near the 0.25 cutoff can flip either way. Measured: Python alone,
        // switching OpenCV INTER_LINEAR to INTER_AREA, also matched only 77/87, all flips at
        // confidence 0.25-0.42. A real bug would lose confident boxes or misplace matched ones.
        XCTAssertEqual(missedConfident, [], "confident reference boxes Swift did not find")
        XCTAssertGreaterThanOrEqual(Double(matched), 0.85 * Double(referenceBoxes))
        XCTAssertLessThanOrEqual(Double(swiftOnly), 0.15 * Double(referenceBoxes))
        XCTAssertGreaterThan(meanIoU, 0.9)
    }
}

func boxIoU(_ a: [Double], _ b: [Double]) -> Double {
    let width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    let height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    let intersection = width * height
    let union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return union > 0 ? intersection / union : 0
}
