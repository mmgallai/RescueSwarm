import Foundation
import RescueSwarmGeolocation
#if canImport(FoundationXML)
import FoundationXML
#endif

/// Metadata refers to the decoded upright image and the camera optical axes.
public struct ImageTelemetry: Codable {
    public let image_sha256: String
    public let width: Int
    public let height: Int
    public let captured_at: Date
    public let latitude: Double
    public let longitude: Double
    public let altitude_agl_m: Double
    public let horizontal_fov_deg: Double
    public let vertical_fov_deg: Double
    public let camera_heading_deg: Double
    public let camera_pitch_deg: Double
    public let camera_roll_deg: Double
    public let ground_hae_m: Double?
}

public struct TelemetryManifest: Decodable {
    public let schema_version: Int
    public let images: [ImageTelemetry]

    public static func load(_ data: Data) throws -> TelemetryManifest {
        guard data.count <= 4 * 1024 * 1024 else { throw WireError.invalidPayload }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let manifest = try decoder.decode(Self.self, from: data)
        guard manifest.schema_version == 1, !manifest.images.isEmpty, manifest.images.count <= 500,
              Set(manifest.images.map(\.image_sha256)).count == manifest.images.count else {
            throw WireError.invalidHeader
        }
        for row in manifest.images {
            let finite = [row.latitude, row.longitude, row.altitude_agl_m, row.horizontal_fov_deg,
                          row.vertical_fov_deg, row.camera_heading_deg, row.camera_pitch_deg, row.camera_roll_deg]
            guard row.image_sha256.count == 64,
                  row.image_sha256.allSatisfy({ "0123456789abcdef".contains($0) }),
                  row.width > 0, row.height > 0, finite.allSatisfy(\.isFinite),
                  (-90...90).contains(row.latitude), (-180...180).contains(row.longitude),
                  row.altitude_agl_m > 0,
                  row.horizontal_fov_deg > 0, row.horizontal_fov_deg < 180,
                  row.vertical_fov_deg > 0, row.vertical_fov_deg < 180,
                  row.ground_hae_m?.isFinite ?? true else { throw WireError.invalidHeader }
        }
        return manifest
    }

    public func match(_ batch: ImageBatch) -> [String: ImageTelemetry] {
        let byHash = Dictionary(uniqueKeysWithValues: images.map { ($0.image_sha256, $0) })
        return Dictionary(uniqueKeysWithValues: batch.items.compactMap { item in
            byHash[item.sha256].map { (item.imageID, $0) }
        })
    }
}

public struct Sighting: Codable, Identifiable {
    public let id: String
    public let image_id: String
    public let detection_index: Int
    public let confidence: Double
    public let latitude: Double?
    public let longitude: Double?
    public let cot_xml: String?
    public let issue: String?
    public let captured_at: Date?

    public static func locate(_ message: Message, runID: UUID, telemetry: ImageTelemetry?) -> [Sighting] {
        let detections = message.detections ?? []
        return detections.enumerated().map { index, detection in
            let uid = "rescueswarm-\(runID.uuidString)-\(message.task_id ?? -1)-\(index)"
            var xml: String?
            var point: CoTPoint?
            var issue: String?
            do {
                guard message.synthetic != true else { throw GeolocationError.invalidInput("Synthetic detection") }
                guard let telemetry else { throw GeolocationError.invalidInput("Missing image telemetry") }
                guard let size = message.image_size,
                      size.width == telemetry.width, size.height == telemetry.height else {
                    throw GeolocationError.invalidInput("Telemetry dimensions differ from the upright image")
                }
                let input = DetectionResult(status: message.status ?? "", imageSize: DetectionImageSize(width: size.width, height: size.height),
                    detections: detections.map { PersonDetection(label: $0.label, confidence: $0.confidence, boxXYXY: $0.box_xyxy) })
                let generated = try geolocatePerson(input, cameraLatitude: telemetry.latitude,
                    cameraLongitude: telemetry.longitude, altitudeMeters: telemetry.altitude_agl_m,
                    horizontalFOVDegrees: telemetry.horizontal_fov_deg, verticalFOVDegrees: telemetry.vertical_fov_deg,
                    headingDegrees: telemetry.camera_heading_deg, detectionIndex: index,
                    flatGroundHAEMeters: telemetry.ground_hae_m, cameraPitchDegrees: telemetry.camera_pitch_deg,
                    cameraRollDegrees: telemetry.camera_roll_deg, uid: uid, now: telemetry.captured_at)
                let parsed = CoTPoint()
                let parser = XMLParser(data: Data(generated.utf8))
                parser.delegate = parsed
                guard parser.parse(), parsed.latitude != nil, parsed.longitude != nil else {
                    throw GeolocationError.invalidInput("Invalid geolocation output")
                }
                xml = generated
                point = parsed
            } catch { issue = error.localizedDescription }
            return Sighting(id: uid, image_id: message.image_id ?? "", detection_index: index,
                confidence: detection.confidence, latitude: point?.latitude, longitude: point?.longitude,
                cot_xml: xml, issue: issue, captured_at: telemetry?.captured_at)
        }
    }
}

private final class CoTPoint: NSObject, XMLParserDelegate {
    var latitude: Double?
    var longitude: Double?
    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String]) {
        if elementName == "point" {
            latitude = attributeDict["lat"].flatMap(Double.init)
            longitude = attributeDict["lon"].flatMap(Double.init)
        }
    }
}
