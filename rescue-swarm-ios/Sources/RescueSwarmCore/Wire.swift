import Foundation

public enum WireError: Error { case invalidHeader, invalidPayload, invalidResult }

public struct Detection: Codable, Equatable {
    public var label: String
    public var confidence: Double
    public var box_xyxy: [Double]
}

// Explicit snake_case matches the existing Python protocol, including optional fields.
public struct Message: Codable {
    public var type: String
    public var payload_bytes: Int = 0
    public var version: Int?
    public var worker_id: String?
    public var task_id: Int?
    public var attempt_id: Int?
    public var image_id: String?
    public var sha256: String?
    public var status: String?
    public var processing_ms: Double?
    public var detections: [Detection]?
    public var synthetic: Bool?
    public var detector: String?
    public init(type: String) { self.type = type }
}

public struct Frame {
    public let message: Message
    public let payload: Data
    public init(_ message: Message, payload: Data = Data()) {
        self.message = message
        self.payload = payload
    }
}

public enum Wire {
    public static let maxHeader = 64 * 1024
    public static let maxPayload = 16 * 1024 * 1024

    public static func encode(_ frame: Frame) throws -> Data {
        guard frame.payload.count <= maxPayload else { throw WireError.invalidPayload }
        var message = frame.message
        message.payload_bytes = frame.payload.count
        let header = try JSONEncoder().encode(message)
        guard !header.isEmpty, header.count <= maxHeader else { throw WireError.invalidHeader }
        let n = UInt32(header.count)
        var data = Data([UInt8((n >> 24) & 255), UInt8((n >> 16) & 255),
                         UInt8((n >> 8) & 255), UInt8(n & 255)])
        data.append(header)
        data.append(frame.payload)
        return data
    }
}

// Incremental parser: never discard a partial frame on a heartbeat or UI event.
public struct FrameDecoder {
    private var buffer = Data()
    public init() {}
    public mutating func append(_ bytes: Data) throws -> [Frame] {
        buffer.append(bytes)
        var frames: [Frame] = []
        while buffer.count >= 4 {
            let prefix = Array(buffer.prefix(4))
            let length = prefix.reduce(0) { ($0 << 8) | Int($1) }
            guard length > 0, length <= Wire.maxHeader else { throw WireError.invalidHeader }
            guard buffer.count >= 4 + length else { break }
            let header = Data(buffer.dropFirst(4).prefix(length))
            let message = try JSONDecoder().decode(Message.self, from: header)
            guard (0...Wire.maxPayload).contains(message.payload_bytes) else { throw WireError.invalidPayload }
            let total = 4 + length + message.payload_bytes
            guard buffer.count >= total else { break }
            frames.append(Frame(message, payload: Data(buffer.dropFirst(4 + length).prefix(message.payload_bytes))))
            buffer = Data(buffer.dropFirst(total))
        }
        return frames
    }
    public var hasIncompleteFrame: Bool { !buffer.isEmpty }
}
