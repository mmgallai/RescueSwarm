import Foundation

public struct DiscoveredSession: Identifiable, Equatable, Hashable {
    public let name: String
    public let type: String
    public let domain: String
    // Length prefixes avoid ambiguous identities when names contain punctuation.
    public var id: String { [name, type, domain].map { "\($0.utf8.count):\($0)" }.joined() }
    public init(name: String, type: String, domain: String) {
        self.name = name
        self.type = type.hasSuffix(".") ? String(type.dropLast()) : type
        self.domain = domain
    }
}

/// Framework-independent state. A cancelled browser must never repopulate the list.
public struct DiscoveryState {
    public static let serviceType = "_rescueswarm._tcp"
    public private(set) var generation = UUID()
    public private(set) var searching = false
    public private(set) var sessions: [DiscoveredSession] = []
    public private(set) var problem: String?
    public init() {}
    @discardableResult public mutating func begin() -> UUID {
        generation = UUID(); searching = true; sessions = []; problem = nil
        return generation
    }
    public mutating func stop() {
        generation = UUID(); searching = false; sessions = []; problem = nil
    }
    public mutating func update(_ values: [DiscoveredSession], generation token: UUID) {
        guard token == generation, searching else { return }
        sessions = Set(values.filter { $0.type == Self.serviceType && !$0.name.isEmpty })
            .sorted { $0.name == $1.name ? $0.id < $1.id : $0.name < $1.name }
    }
    public mutating func fail(_ reason: String, generation token: UUID) {
        guard token == generation, searching else { return }
        sessions = []; searching = false; problem = reason
    }
}
