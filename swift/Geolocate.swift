import Foundation

public struct DetectionImageSize: Decodable {
    public let width: Int
    public let height: Int

    public init(width: Int, height: Int) {
        self.width = width
        self.height = height
    }
}

public struct PersonDetection: Decodable {
    public let label: String
    public let confidence: Double
    public let boxXYXY: [Double]

    public init(label: String = "person", confidence: Double, boxXYXY: [Double]) {
        self.label = label
        self.confidence = confidence
        self.boxXYXY = boxXYXY
    }

    private enum CodingKeys: String, CodingKey {
        case label
        case confidence
        case boxXYXY = "box_xyxy"
    }
}

public struct DetectionResult: Decodable {
    public let status: String
    public let imageSize: DetectionImageSize?
    public let detections: [PersonDetection]

    public init(status: String, imageSize: DetectionImageSize?, detections: [PersonDetection]) {
        self.status = status
        self.imageSize = imageSize
        self.detections = detections
    }

    private enum CodingKeys: String, CodingKey {
        case status
        case imageSize = "image_size"
        case detections
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        status = try values.decode(String.self, forKey: .status)
        imageSize = try values.decodeIfPresent(DetectionImageSize.self, forKey: .imageSize)
        detections = try values.decodeIfPresent([PersonDetection].self, forKey: .detections) ?? []
    }
}

public enum GeolocationError: Error, LocalizedError {
    case invalidInput(String)
    case unsuccessfulResult
    case missingImageSize
    case detectionIndexOutOfRange
    case invalidDetection(String)
    case cameraTooCloseToPole

    public var errorDescription: String? {
        switch self {
        case .invalidInput(let message), .invalidDetection(let message):
            return message
        case .unsuccessfulResult:
            return "message must contain a successful detection result"
        case .missingImageSize:
            return "message must include image dimensions"
        case .detectionIndexOutOfRange:
            return "detection index is out of range"
        case .cameraTooCloseToPole:
            return "camera latitude is too close to a pole for this local projection"
        }
    }
}

public typealias ElevationProvider = (_ latitude: Double, _ longitude: Double) throws -> Double?

public let cotUnknown = 9999999.0

public enum TerrainDatum { case msl, hae }

private let earthRadiusMeters = 6_371_000.0
private let personLabel = "person"
private let successStatus = "success"

/// Estimates a detection's ground position and returns a Cursor on Target XML event.
/// Nadir camera only. altitudeMeters is AGL above terrain beneath the camera.
/// Provider elevations must share terrainDatum. HAE = MSL + geoidOffsetMeters.
/// Pass a stable explicit UID for updates; nil creates a new sighting.
/// Bottom-center of the box is an anchor assumption, not verified person ground truth.
public func geolocatePerson(
    _ message: DetectionResult,
    cameraLatitude: Double,
    cameraLongitude: Double,
    altitudeMeters: Double,
    horizontalFOVDegrees: Double,
    verticalFOVDegrees: Double,
    headingDegrees: Double = 0,
    detectionIndex: Int = 0,
    elevationProvider: ElevationProvider? = nil,
    terrainDatum: TerrainDatum = .msl,
    geoidOffsetMeters: Double? = nil,
    flatGroundHAEMeters: Double? = nil,
    cameraPitchDegrees: Double = -90,
    cameraRollDegrees: Double = 0,
    uid: String? = nil,
    staleDurationSeconds: Int = 60,
    now: Date = Date(),
    warningHandler: ((String) -> Void)? = nil
) throws -> String {
    try validateCamera(
        latitude: cameraLatitude,
        longitude: cameraLongitude,
        altitude: altitudeMeters,
        horizontalFOV: horizontalFOVDegrees,
        verticalFOV: verticalFOVDegrees,
        heading: headingDegrees
    )

    guard cameraPitchDegrees.isFinite, cameraRollDegrees.isFinite,
          abs(cameraPitchDegrees + 90) < 1e-6, abs(cameraRollDegrees) < 1e-6 else {
        throw GeolocationError.invalidInput("only nadir camera pitch=-90 and roll=0 are supported")
    }
    guard [geoidOffsetMeters, flatGroundHAEMeters].compactMap({ $0 }).allSatisfy(\.isFinite) else {
        throw GeolocationError.invalidInput("height conversion values must be finite")
    }
    if let uid, uid.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        throw GeolocationError.invalidInput("uid must be nonempty")
    }
    guard (1...86400).contains(staleDurationSeconds), now.timeIntervalSince1970.isFinite else {
        throw GeolocationError.invalidInput("invalid event time or stale duration")
    }
    let sightingUID = uid ?? "rescueswarm-" + UUID().uuidString
    let longitudeScale = cos(degreesToRadians(cameraLatitude))
    guard abs(longitudeScale) >= 1e-6 else { throw GeolocationError.cameraTooCloseToPole }

    guard message.status == successStatus else {
        throw GeolocationError.unsuccessfulResult
    }
    guard let imageSize = message.imageSize else {
        throw GeolocationError.missingImageSize
    }
    guard detectionIndex >= 0, detectionIndex < message.detections.count else {
        throw GeolocationError.detectionIndexOutOfRange
    }
    guard imageSize.width > 0, imageSize.height > 0 else {
        throw GeolocationError.invalidInput("image dimensions must be positive")
    }

    let detection = message.detections[detectionIndex]
    guard detection.label == personLabel else {
        throw GeolocationError.invalidDetection("only person detections are allowed")
    }
    guard detection.confidence.isFinite, (0...1).contains(detection.confidence) else {
        throw GeolocationError.invalidDetection("confidence must be finite and in [0, 1]")
    }
    guard detection.boxXYXY.count == 4,
          detection.boxXYXY.allSatisfy(\.isFinite) else {
        throw GeolocationError.invalidDetection("box must contain 4 finite numbers")
    }

    let x1 = detection.boxXYXY[0]
    let y1 = detection.boxXYXY[1]
    let x2 = detection.boxXYXY[2]
    let y2 = detection.boxXYXY[3]
    guard 0 <= x1, x1 < x2, x2 <= Double(imageSize.width),
          0 <= y1, y1 < y2, y2 <= Double(imageSize.height) else {
        throw GeolocationError.invalidDetection("box must be within the image and have positive area")
    }

    let pixelX = (x1 + x2) / 2
    let pixelY = y2
    let tangentHorizontal = tan(degreesToRadians(horizontalFOVDegrees) / 2)
    let tangentVertical = tan(degreesToRadians(verticalFOVDegrees) / 2)
    let rayRight = (pixelX / Double(imageSize.width) - 0.5) * 2 * tangentHorizontal
    let rayUp = (0.5 - pixelY / Double(imageSize.height)) * 2 * tangentVertical

    let heading = degreesToRadians(headingDegrees)
    let eastUnit = rayRight * cos(heading) + rayUp * sin(heading)
    let northUnit = -rayRight * sin(heading) + rayUp * cos(heading)
    let downUnit = 1.0
    let rayLength = sqrt(eastUnit * eastUnit + northUnit * northUnit + downUnit * downUnit)
    let directionEast = eastUnit / rayLength
    let directionNorth = northUnit / rayLength
    let directionDown = downUnit / rayLength

    func project(_ distance: Double) throws -> (latitude: Double, longitude: Double) {
        let lat = cameraLatitude + radiansToDegrees(distance * directionNorth / earthRadiusMeters)
        let lon = cameraLongitude + radiansToDegrees(distance * directionEast / (earthRadiusMeters * longitudeScale))
        guard (-90...90).contains(lat) else { throw GeolocationError.invalidInput("projection crosses a pole") }
        let normalized = ((lon + 180).truncatingRemainder(dividingBy: 360) + 360).truncatingRemainder(dividingBy: 360) - 180
        return (lat, normalized)
    }
    var ground: Double?
    if let elevationProvider {
        do {
            ground = try elevationProvider(cameraLatitude, cameraLongitude)
            if ground == nil { warningHandler?("Elevation data unavailable. Falling back to flat-ground assumption.") }
        } catch {
            warningHandler?("Elevation lookup failed: \(error). Falling back to flat-ground assumption.")
        }
        if let ground, !ground.isFinite { throw GeolocationError.invalidInput("terrain elevation must be finite") }
    }
    let location: (latitude: Double, longitude: Double, hae: Double)
    let method: String
    if let ground, let elevationProvider {
        let cameraAltitude = ground + altitudeMeters
        func sample(_ distance: Double) throws -> Double {
            let position = try project(distance)
            guard let terrain = try elevationProvider(position.latitude, position.longitude), terrain.isFinite else {
                throw GeolocationError.invalidInput("terrain unavailable or invalid along ray")
            }
            return cameraAltitude - distance * directionDown - terrain
        }
        let step = max(1.0, min(5.0, altitudeMeters / 20))
        var low = 0.0
        var crossing: Double?
        for i in 1...2000 {
            let candidate = Double(i) * step
            if try sample(candidate) <= 0 { crossing = candidate; break }
            low = candidate
        }
        guard var high = crossing else {
            throw GeolocationError.invalidInput("no terrain intersection within bounded search")
        }
        while high - low > 0.01 {
            let middle = (low + high) / 2
            if try sample(middle) > 0 { low = middle } else { high = middle }
        }
        let distance = (low + high) / 2
        guard abs(try sample(distance)) <= 0.1 else {
            throw GeolocationError.invalidInput("terrain intersection unresolved at discontinuity")
        }
        let position = try project(distance)
        let hitHeight = cameraAltitude - distance * directionDown
        let hae: Double
        switch terrainDatum {
        case .hae: hae = hitHeight
        case .msl: hae = geoidOffsetMeters.map { hitHeight + $0 } ?? cotUnknown
        }
        location = (position.latitude, position.longitude, hae)
        method = "terrain intersection"
    } else {
        let distance = altitudeMeters / directionDown
        guard distance <= 10000 else { throw GeolocationError.invalidInput("projection exceeds local 10 km range") }
        let position = try project(distance)
        location = (position.latitude, position.longitude, flatGroundHAEMeters ?? cotUnknown)
        method = "flat-ground assumption"
    }

    guard location.hae.isFinite else { throw GeolocationError.invalidInput("converted HAE must be finite") }

    return makeCoTEvent(
        latitude: location.latitude,
        longitude: location.longitude,
        hae: location.hae,
        confidence: detection.confidence,
        uid: sightingUID,
        method: method,
        now: now,
        staleDurationSeconds: staleDurationSeconds
    )
}

private func validateCamera(
    latitude: Double,
    longitude: Double,
    altitude: Double,
    horizontalFOV: Double,
    verticalFOV: Double,
    heading: Double
) throws {
    guard latitude.isFinite, (-90...90).contains(latitude) else {
        throw GeolocationError.invalidInput("camera latitude must be finite and in [-90, 90]")
    }
    guard longitude.isFinite, (-180...180).contains(longitude) else {
        throw GeolocationError.invalidInput("camera longitude must be finite and in [-180, 180]")
    }
    guard altitude.isFinite, altitude > 0 else {
        throw GeolocationError.invalidInput("altitude must be finite and positive")
    }
    guard horizontalFOV.isFinite, 0 < horizontalFOV, horizontalFOV < 180 else {
        throw GeolocationError.invalidInput("horizontal FOV must be in (0, 180)")
    }
    guard verticalFOV.isFinite, 0 < verticalFOV, verticalFOV < 180 else {
        throw GeolocationError.invalidInput("vertical FOV must be in (0, 180)")
    }
    guard heading.isFinite else {
        throw GeolocationError.invalidInput("heading must be finite")
    }
}

private func makeCoTEvent(
    latitude: Double,
    longitude: Double,
    hae: Double,
    confidence: Double,
    uid: String,
    method: String,
    now: Date,
    staleDurationSeconds: Int
) -> String {
    let time = formatCoTDate(now)
    let stale = formatCoTDate(now.addingTimeInterval(TimeInterval(staleDurationSeconds)))
    let callsign = escapeXML(String(format: "Detected Person (%.2f)", locale: Locale(identifier: "en_US_POSIX"), arguments: [confidence]))
    let remarks = escapeXML(String(format: "Rescueswarm Vision Detection. Confidence: %.1f%%. ", locale: Locale(identifier: "en_US_POSIX"), arguments: [confidence * 100]) + method + "; nadir camera. " + (hae == cotUnknown ? "Height unknown." : "Height is HAE."))

    return """
    <event version="2.0" uid="\(escapeXML(uid))" type="a-u-G" time="\(time)" start="\(time)" stale="\(stale)" how="m-g"><point lat="\(formatNumber(latitude, decimals: 6))" lon="\(formatNumber(longitude, decimals: 6))" hae="\(formatNumber(hae, decimals: 1))" ce="9999999.0" le="9999999.0"/><detail><contact callsign="\(callsign)"/><remarks>\(remarks)</remarks></detail></event>
    """
    .trimmingCharacters(in: .whitespacesAndNewlines)
}

private func formatCoTDate(_ date: Date) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.string(from: date)
}

private func formatNumber(_ value: Double, decimals: Int) -> String {
    String(
        format: "%.*f",
        locale: Locale(identifier: "en_US_POSIX"),
        arguments: [decimals, value]
    )
}

private func escapeXML(_ value: String) -> String {
    value
        .replacingOccurrences(of: "&", with: "&amp;")
        .replacingOccurrences(of: "<", with: "&lt;")
        .replacingOccurrences(of: ">", with: "&gt;")
        .replacingOccurrences(of: "\"", with: "&quot;")
        .replacingOccurrences(of: "'", with: "&apos;")
}

private func degreesToRadians(_ degrees: Double) -> Double {
    degrees * .pi / 180
}

private func radiansToDegrees(_ radians: Double) -> Double {
    radians * 180 / .pi
}