import CoreGraphics
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

final class PersonDetectorModelTests: XCTestCase {
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
