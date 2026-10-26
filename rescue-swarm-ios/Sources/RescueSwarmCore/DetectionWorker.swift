import Foundation

/// Turns one task's image into a result message, like Worker.handle() in the Python worker.
/// Never throws: an undecodable image or a model error becomes a "failure" result.
public enum DetectionWorker {
    public static let detectorName = "yolo26n"
    public static let confidenceThreshold = 0.25
    public static let config = DetectorConfig(model: detectorName, imgsz: PersonDetector.defaultInputSize,
                                              conf: confidenceThreshold, runtime: "coreml")

    public static func process(_ image: Data, task: Int, attempt: Int, imageID: String,
                               detector: PersonDetector) -> Message {
        let started = DispatchTime.now()
        var result = Message(type: "result")
        result.task_id = task; result.attempt_id = attempt; result.image_id = imageID
        result.synthetic = false; result.detector = detectorName; result.detector_config = config
        do {
            let detected = try detector.detect(imageData: image, confidenceThreshold: confidenceThreshold)
            result.status = "success"
            result.detections = detected.detections
            result.image_size = ImageSize(width: detected.imageWidth, height: detected.imageHeight)
        } catch {
            result.status = "failure"
            result.detections = []
            result.error = String(describing: error)
        }
        result.processing_ms = Double(DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds) / 1_000_000
        return result
    }
}
