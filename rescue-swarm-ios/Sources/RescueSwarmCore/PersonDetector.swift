import CoreGraphics
import CoreML
import CoreVideo
import Foundation
import ImageIO

// Swift port of rescueswarm/coreml_reference.py (evi/detection-worker branch). The bundled
// YOLO26n model takes a fixed square RGB image, so photos are letterboxed: shrunk to fit,
// centered, and padded with gray. Keep both versions in step.

public enum DetectorError: Error, Equatable {
    case undecodableImage
    case pixelBufferUnavailable
    case missingModelOutput(String)
}

/// Where an original width x height photo sits inside the size x size model input.
public struct Letterbox: Equatable {
    public let scale: Double  // input pixels per original pixel
    public let left: Int      // padding columns on the left
    public let top: Int       // padding rows on top
    public let resizedWidth: Int
    public let resizedHeight: Int
    public let size: Int

    public static func fit(width: Int, height: Int, size: Int) -> Letterbox {
        let scale = min(Double(size) / Double(width), Double(size) / Double(height))
        // .toNearestOrEven matches Python's round().
        let resizedWidth = Int((Double(width) * scale).rounded(.toNearestOrEven))
        let resizedHeight = Int((Double(height) * scale).rounded(.toNearestOrEven))
        return Letterbox(scale: scale, left: (size - resizedWidth) / 2, top: (size - resizedHeight) / 2,
                         resizedWidth: resizedWidth, resizedHeight: resizedHeight, size: size)
    }

    /// Model-input pixel -> original-photo pixel.
    public func toOriginal(x: Double, y: Double) -> (x: Double, y: Double) {
        ((x - Double(left)) / scale, (y - Double(top)) / scale)
    }
}

/// A photo ready for the model: letterboxed pixels plus what is needed to map boxes back.
public struct PreparedImage {
    public let pixelBuffer: CVPixelBuffer
    public let letterbox: Letterbox
    public let originalWidth: Int   // upright, i.e. after applying the EXIF orientation
    public let originalHeight: Int
}

public enum ImagePreparation {
    public static let padGray: CGFloat = 114 / 255  // same padding value as Ultralytics

    /// Decode JPEG/PNG bytes upright and letterbox them into a size x size BGRA pixel buffer.
    /// ImageIO decodes straight to the target size, so a 20-megapixel photo is never fully expanded.
    public static func prepare(_ data: Data, size: Int) throws -> PreparedImage {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let storedWidth = properties[kCGImagePropertyPixelWidth] as? Int,
              let storedHeight = properties[kCGImagePropertyPixelHeight] as? Int
        else { throw DetectorError.undecodableImage }

        // EXIF orientations 5-8 rotate by 90 degrees, so the upright photo swaps width and height.
        let orientation = properties[kCGImagePropertyOrientation] as? Int ?? 1
        let (width, height) = orientation >= 5 ? (storedHeight, storedWidth) : (storedWidth, storedHeight)
        let box = Letterbox.fit(width: width, height: height, size: size)

        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,  // apply the EXIF orientation
            kCGImageSourceThumbnailMaxPixelSize: max(box.resizedWidth, box.resizedHeight),
            kCGImageSourceShouldCacheImmediately: true,
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
        else { throw DetectorError.undecodableImage }

        return PreparedImage(pixelBuffer: try letterboxedBuffer(image, box), letterbox: box,
                             originalWidth: width, originalHeight: height)
    }

    static func letterboxedBuffer(_ image: CGImage, _ box: Letterbox) throws -> CVPixelBuffer {
        var buffer: CVPixelBuffer?
        let attributes = [kCVPixelBufferCGImageCompatibilityKey: true,
                          kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary
        guard CVPixelBufferCreate(nil, box.size, box.size, kCVPixelFormatType_32BGRA, attributes, &buffer)
                == kCVReturnSuccess, let buffer else { throw DetectorError.pixelBufferUnavailable }

        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(buffer), width: box.size, height: box.size,
            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { throw DetectorError.pixelBufferUnavailable }

        context.setFillColor(red: padGray, green: padGray, blue: padGray, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: box.size, height: box.size))
        context.interpolationQuality = .high
        // Core Graphics puts y = 0 at the bottom, so flip the top padding.
        let y = box.size - box.top - box.resizedHeight
        context.draw(image, in: CGRect(x: box.left, y: y, width: box.resizedWidth, height: box.resizedHeight))
        return buffer
    }
}

/// Raw output of the bundled model after its built-in NMS, one row per box.
public struct ModelOutput {
    public let coordinates: MLMultiArray  // (N, 4): center x, center y, width, height, fractions of the input
    public let confidence: MLMultiArray   // (N, 80): score per COCO class; column 0 is "person"
}

public enum OutputDecoding {
    public static let personClass = 0  // "person" in the COCO classes YOLO is trained on

    /// One model row: box (center x, center y, width, height as fractions of the input) and 80 class scores.
    public typealias Row = (box: [Double], scores: [Double])

    /// Person detections in original-photo pixels, clipped to the photo.
    public static func decode(_ rows: [Row], letterbox: Letterbox, originalWidth: Int, originalHeight: Int,
                              confidenceThreshold: Double) -> [Detection] {
        let size = Double(letterbox.size)
        var detections: [Detection] = []
        for (box, scores) in rows {
            guard let best = scores.indices.max(by: { scores[$0] < scores[$1] }), best == personClass,
                  scores[personClass] >= confidenceThreshold else { continue }
            let (cx, cy, w, h) = (box[0], box[1], box[2], box[3])
            let topLeft = letterbox.toOriginal(x: (cx - w / 2) * size, y: (cy - h / 2) * size)
            let bottomRight = letterbox.toOriginal(x: (cx + w / 2) * size, y: (cy + h / 2) * size)
            // Clip to the photo: a box can reach into the padding.
            let x1 = max(0, topLeft.x), y1 = max(0, topLeft.y)
            let x2 = min(Double(originalWidth), bottomRight.x), y2 = min(Double(originalHeight), bottomRight.y)
            if x1 < x2 && y1 < y2 {
                detections.append(Detection(label: "person", confidence: scores[personClass],
                                            box_xyxy: [x1, y1, x2, y2]))
            }
        }
        return detections
    }

    /// Read the model's (N, 4) and (N, 80) outputs into rows.
    public static func rows(from output: ModelOutput) -> [Row] {
        let count = output.coordinates.shape.first?.intValue ?? 0
        let classes = output.confidence.shape.last?.intValue ?? 0
        func value(_ array: MLMultiArray, _ i: Int, _ j: Int) -> Double {
            array[[NSNumber(value: i), NSNumber(value: j)]].doubleValue
        }
        return (0..<count).map { i in
            ((0..<4).map { value(output.coordinates, i, $0) }, (0..<classes).map { value(output.confidence, i, $0) })
        }
    }
}

/// What the detector reports for one image.
public struct DetectorResult {
    public let detections: [Detection]
    public let imageWidth: Int   // upright original size, for the result's image_size
    public let imageHeight: Int
    public let elapsedMs: Double // decode + letterbox + model + box mapping
}

/// Runs the bundled YOLO26n Core ML model.
public final class PersonDetector {
    public static let defaultInputSize = 1280
    public static let iouThreshold = 0.7  // NMS inside the model; Ultralytics' default

    public let model: MLModel
    public let inputSize: Int

    public init(model: MLModel, inputSize: Int = PersonDetector.defaultInputSize) {
        self.model = model
        self.inputSize = inputSize
    }

    /// Load a compiled model (.mlmodelc, as bundled in the app) or compile an .mlpackage first.
    public static func load(from url: URL, computeUnits: MLComputeUnits = .all) async throws -> PersonDetector {
        let compiled = url.pathExtension == "mlmodelc" ? url : try await MLModel.compileModel(at: url)
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        return PersonDetector(model: try MLModel(contentsOf: compiled, configuration: configuration))
    }

    /// Find people in JPEG/PNG bytes. Boxes are in the upright original photo's pixels.
    public func detect(imageData: Data, confidenceThreshold: Double = 0.25) throws -> DetectorResult {
        let started = DispatchTime.now()
        let image = try ImagePreparation.prepare(imageData, size: inputSize)
        let output = try runModel(on: image, confidenceThreshold: confidenceThreshold)
        let detections = OutputDecoding.decode(OutputDecoding.rows(from: output), letterbox: image.letterbox,
                                               originalWidth: image.originalWidth,
                                               originalHeight: image.originalHeight,
                                               confidenceThreshold: confidenceThreshold)
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds) / 1_000_000
        return DetectorResult(detections: detections, imageWidth: image.originalWidth,
                              imageHeight: image.originalHeight, elapsedMs: elapsedMs)
    }

    public func runModel(on image: PreparedImage, confidenceThreshold: Double) throws -> ModelOutput {
        let input = try MLDictionaryFeatureProvider(dictionary: [
            "image": MLFeatureValue(pixelBuffer: image.pixelBuffer),
            "iouThreshold": MLFeatureValue(double: Self.iouThreshold),
            "confidenceThreshold": MLFeatureValue(double: confidenceThreshold),
        ])
        let output = try model.prediction(from: input)
        guard let coordinates = output.featureValue(for: "coordinates")?.multiArrayValue
        else { throw DetectorError.missingModelOutput("coordinates") }
        guard let confidence = output.featureValue(for: "confidence")?.multiArrayValue
        else { throw DetectorError.missingModelOutput("confidence") }
        return ModelOutput(coordinates: coordinates, confidence: confidence)
    }
}
