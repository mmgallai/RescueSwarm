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

private let earthRadiusMeters = 6_371_000.0
private let personLabel = "person"
private let successStatus = "success"

/// Estimates a detection's ground position and returns a Cursor on Target XML event.
/// Pass an elevation provider for terrain ray marching; nil uses flat-ground projection.
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
    uid: String = "rescueswarm-target-01",
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

    let location: (latitude: Double, longitude: Double, hae: Double)
    var cameraGroundElevation: Double?
    var useFlatGround = true

    if let elevationProvider {
        do {
            cameraGroundElevation = try elevationProvider(cameraLatitude, cameraLongitude)
            useFlatGround = cameraGroundElevation == nil
            if useFlatGround {
                warningHandler?("Elevation data unavailable for camera position. Falling back to flat-ground assumption.")
            }
        } catch {
            warningHandler?("Elevation lookup failed with error: \(error). Falling back to flat-ground assumption.")
        }
    }

    if useFlatGround {
        let rightMeters = rayRight * altitudeMeters
        let upMeters = rayUp * altitudeMeters
        let eastMeters = rightMeters * cos(heading) + upMeters * sin(heading)
        let northMeters = -rightMeters * sin(heading) + upMeters * cos(heading)
        let longitudeScale = cos(degreesToRadians(cameraLatitude))
        guard abs(longitudeScale) >= 1e-12 else {
            throw GeolocationError.cameraTooCloseToPole
        }
        location = (
            latitude: cameraLatitude + radiansToDegrees(northMeters / earthRadiusMeters),
            longitude: cameraLongitude + radiansToDegrees(eastMeters / (earthRadiusMeters * longitudeScale)),
            hae: 0
        )
    } else {
        guard let elevationProvider, let cameraGroundElevation else {
            throw GeolocationError.invalidInput("elevation provider did not provide camera elevation")
        }

        let cameraAltitudeMSL = cameraGroundElevation + altitudeMeters
        var currentAltitudeMSL = cameraAltitudeMSL
        var currentLatitude = cameraLatitude
        var currentLongitude = cameraLongitude
        let stepDistance = altitudeMeters / 20

        for _ in 0..<100 {
            let terrainElevation = try elevationProvider(currentLatitude, currentLongitude) ?? cameraGroundElevation
            if currentAltitudeMSL <= terrainElevation {
                break
            }

            currentAltitudeMSL -= stepDistance * directionDown
            let traveledDown = cameraAltitudeMSL - currentAltitudeMSL
            let totalEast = traveledDown * (directionEast / directionDown)
            let totalNorth = traveledDown * (directionNorth / directionDown)
            let longitudeScale = cos(degreesToRadians(cameraLatitude))
            guard abs(longitudeScale) >= 1e-12 else {
                throw GeolocationError.cameraTooCloseToPole
            }
            currentLatitude = cameraLatitude + radiansToDegrees(totalNorth / earthRadiusMeters)
            currentLongitude = cameraLongitude + radiansToDegrees(totalEast / (earthRadiusMeters * longitudeScale))
        }

        location = (currentLatitude, currentLongitude, currentAltitudeMSL)
    }

    return makeCoTEvent(
        latitude: location.latitude,
        longitude: location.longitude,
        hae: location.hae,
        confidence: detection.confidence,
        uid: uid,
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
    now: Date,
    staleDurationSeconds: Int
) -> String {
    let time = formatCoTDate(now)
    let stale = formatCoTDate(now.addingTimeInterval(TimeInterval(staleDurationSeconds)))
    let callsign = escapeXML(String(format: "Detected Person (%.2f)", locale: Locale(identifier: "en_US_POSIX"), arguments: [confidence]))
    let remarks = escapeXML(String(format: "Rescueswarm Vision Detection. Confidence: %.1f%%", locale: Locale(identifier: "en_US_POSIX"), arguments: [confidence * 100]))

    return """
    <event version="2.0" uid="\(escapeXML(uid))" type="a-u-G" time="\(time)" start="\(time)" stale="\(stale)" how="m-g"><point lat="\(formatNumber(latitude, decimals: 6))" lon="\(formatNumber(longitude, decimals: 6))" hae="\(formatNumber(hae, decimals: 1))" ce="999.0" le="999.0"/><detail><contact callsign="\(callsign)"/><remarks>\(remarks)</remarks></detail></event>
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