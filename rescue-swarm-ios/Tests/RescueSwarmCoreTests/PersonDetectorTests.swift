import CoreGraphics
import CoreML
import CoreVideo
import Foundation
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import RescueSwarmCore

final class LetterboxTests: XCTestCase {
    // Same cases as tests/test_coreml_reference.py on the Python side.
    func testWidePhotoIsPaddedTopAndBottom() {
        let box = Letterbox.fit(width: 5472, height: 3648, size: 1280)  // SAR-DAG photo
        XCTAssertEqual(box.scale, 1280.0 / 5472.0, accuracy: 1e-12)
        XCTAssertEqual([box.resizedWidth, box.resizedHeight, box.left, box.top], [1280, 853, 0, 213])
    }

    func testTallPhotoIsPaddedLeftAndRight() {
        let box = Letterbox.fit(width: 3000, height: 4000, size: 1280)
        XCTAssertEqual([box.resizedWidth, box.resizedHeight, box.left, box.top], [960, 1280, 160, 0])
    }

    func testMappingUndoesScaleAndPadding() {
        let box = Letterbox.fit(width: 5472, height: 3648, size: 1280)
        let topLeft = box.toOriginal(x: 0, y: 213)
        XCTAssertEqual(topLeft.x, 0, accuracy: 1e-9)
        XCTAssertEqual(topLeft.y, 0, accuracy: 1e-9)
        let bottomRight = box.toOriginal(x: 1280, y: 213 + 1280 * 3648 / 5472)
        XCTAssertEqual(bottomRight.x, 5472, accuracy: 1e-6)
        XCTAssertEqual(bottomRight.y, 3648, accuracy: 1e-6)
    }
}

final class ImagePreparationTests: XCTestCase {
    func testWhitePhotoIsCenteredOnGrayPadding() throws {
        let prepared = try ImagePreparation.prepare(jpeg(width: 200, height: 100), size: 64)
        XCTAssertEqual([prepared.originalWidth, prepared.originalHeight], [200, 100])
        XCTAssertEqual([prepared.letterbox.top, prepared.letterbox.resizedHeight], [16, 32])
        XCTAssertEqual(CVPixelBufferGetWidth(prepared.pixelBuffer), 64)
        XCTAssertEqual(CVPixelBufferGetHeight(prepared.pixelBuffer), 64)
        XCTAssertEqual(rgb(prepared.pixelBuffer, x: 0, y: 0), [114, 114, 114])  // padding, top row
        XCTAssertEqual(rgb(prepared.pixelBuffer, x: 0, y: 63), [114, 114, 114]) // padding, bottom row
        XCTAssertEqual(rgb(prepared.pixelBuffer, x: 32, y: 32), [255, 255, 255]) // photo
    }

    func testExifRotationSwapsWidthAndHeight() throws {
        // Stored 200x100 but tagged "rotate 90 degrees" (orientation 6), as phones do for portrait shots.
        let prepared = try ImagePreparation.prepare(jpeg(width: 200, height: 100, orientation: 6), size: 64)
        XCTAssertEqual([prepared.originalWidth, prepared.originalHeight], [100, 200])
        XCTAssertEqual([prepared.letterbox.left, prepared.letterbox.resizedWidth], [16, 32])
        XCTAssertEqual(rgb(prepared.pixelBuffer, x: 32, y: 32), [255, 255, 255])
        XCTAssertEqual(rgb(prepared.pixelBuffer, x: 2, y: 32), [114, 114, 114])  // padding is now left/right
    }

    func testGarbageIsRejected() {
        XCTAssertThrowsError(try ImagePreparation.prepare(Data("not an image".utf8), size: 64)) {
            XCTAssertEqual($0 as? DetectorError, .undecodableImage)
        }
    }
}

final class OutputDecodingTests: XCTestCase {
    // Same cases as tests/test_coreml_reference.py on the Python side.
    let sarDag = Letterbox.fit(width: 5472, height: 3648, size: 1280)

    func scores(person: Double, car: Double = 0) -> [Double] {
        var row = [Double](repeating: 0, count: 80)
        row[0] = person
        row[2] = car
        return row
    }

    func testPersonBoxIsMappedToOriginalPixels() {
        // A box covering the whole photo area inside the square (rows 213 to 1066).
        let rows: [OutputDecoding.Row] = [([0.5, (213 + 853.0 / 2) / 1280, 1.0, 853.0 / 1280], scores(person: 0.9))]
        let detection = OutputDecoding.decode(rows, letterbox: sarDag, originalWidth: 5472,
                                                originalHeight: 3648, confidenceThreshold: 0.25)
        XCTAssertEqual(detection.count, 1)
        XCTAssertEqual(detection[0].label, "person")
        XCTAssertEqual(detection[0].confidence, 0.9)
        // 3648 rows shrink to 853.3, rounded to 853, so edges can be ~1.5 original pixels off.
        for (value, expected) in zip(detection[0].box_xyxy, [0, 0, 5472, 3648.0]) {
            XCTAssertEqual(value, expected, accuracy: 2)
        }
    }

    func testOtherClassesAndWeakPeopleAreDropped() {
        let box = [0.5, 0.5, 0.1, 0.1]
        let rows: [OutputDecoding.Row] = [(box, scores(person: 0.9)), (box, scores(person: 0.1)),
                                          (box, scores(person: 0.3, car: 0.8))]
        let detections = OutputDecoding.decode(rows, letterbox: Letterbox.fit(width: 640, height: 640, size: 640),
                                               originalWidth: 640, originalHeight: 640, confidenceThreshold: 0.25)
        XCTAssertEqual(detections.map(\.confidence), [0.9])
    }

    func testBoxReachingIntoPaddingIsClipped() {
        let rows: [OutputDecoding.Row] = [([0.5, 213.0 / 1280, 0.1, 0.1], scores(person: 0.9))]  // on the top edge
        let detections = OutputDecoding.decode(rows, letterbox: sarDag, originalWidth: 5472,
                                               originalHeight: 3648, confidenceThreshold: 0.25)
        XCTAssertEqual(detections.first?.box_xyxy[1], 0)
    }

    func testRowsAreReadFromModelArrays() throws {
        let coordinates = try MLMultiArray(shape: [2, 4], dataType: .float32)
        let confidence = try MLMultiArray(shape: [2, 80], dataType: .float32)
        for i in 0..<8 { coordinates[i] = NSNumber(value: Float(i) / 10) }
        for i in 0..<160 { confidence[i] = 0 }
        confidence[[1, 0]] = 0.75
        let rows = OutputDecoding.rows(from: ModelOutput(coordinates: coordinates, confidence: confidence))
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows[1].box, [0.4, 0.5, 0.6, 0.7].map { Double(Float($0)) })
        XCTAssertEqual(rows[1].scores[0], 0.75)
        XCTAssertEqual(rows[1].scores.count, 80)
    }
}

final class PersonDetectorModelTests: XCTestCase {
    func testDetectReportsSizeAndTimingAndFindsNobodyInABlankPhoto() async throws {
        let detector = try await PersonDetector.load(from: bundledModelURL, computeUnits: .cpuOnly)
        let result = try detector.detect(imageData: jpeg(width: 640, height: 480))
        XCTAssertEqual(result.detections, [])
        XCTAssertEqual([result.imageWidth, result.imageHeight], [640, 480])
        XCTAssertGreaterThan(result.elapsedMs, 0)
    }

    func testBundledModelRunsAndReturnsBoxesAndClassScores() async throws {
        let detector = try await PersonDetector.load(from: bundledModelURL, computeUnits: .cpuOnly)
        let prepared = try ImagePreparation.prepare(jpeg(width: 640, height: 480), size: detector.inputSize)
        let output = try detector.runModel(on: prepared, confidenceThreshold: 0.25)
        XCTAssertEqual(output.coordinates.shape.last, 4)
        XCTAssertEqual(output.confidence.shape.last, 80)
        XCTAssertEqual(output.coordinates.shape.first, output.confidence.shape.first)
    }
}

// MARK: - Helpers

/// rescue-swarm-ios/App/YOLO26n.mlpackage, found relative to this source file.
let bundledModelURL = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("App/YOLO26n.mlpackage")

/// A solid white JPEG, optionally tagged with an EXIF orientation.
func jpeg(width: Int, height: Int, orientation: Int = 1) -> Data {
    let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.setFillColor(red: 1, green: 1, blue: 1, alpha: 1)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    let data = NSMutableData()
    let destination = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, context.makeImage()!,
                               [kCGImagePropertyOrientation: orientation] as CFDictionary)
    CGImageDestinationFinalize(destination)
    return data as Data
}

/// [r, g, b] at (x, y) in a BGRA pixel buffer, y = 0 at the top.
func rgb(_ buffer: CVPixelBuffer, x: Int, y: Int) -> [UInt8] {
    CVPixelBufferLockBaseAddress(buffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
    let row = CVPixelBufferGetBaseAddress(buffer)!.advanced(by: y * CVPixelBufferGetBytesPerRow(buffer))
    let pixel = row.assumingMemoryBound(to: UInt8.self).advanced(by: x * 4)
    return [pixel[2], pixel[1], pixel[0]]
}
