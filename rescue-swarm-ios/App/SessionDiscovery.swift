import SwiftUI
import Network
import RescueSwarmCore

@MainActor
final class SessionDiscovery: ObservableObject {
    @Published private(set) var state = DiscoveryState()
    private var browser: NWBrowser?
    private var endpoints: [String: NWEndpoint] = [:]

    func start() {
        stop()
        let token = state.begin()
        let browser = NWBrowser(for: .bonjour(type: DiscoveryState.serviceType, domain: nil), using: .tcp)
        self.browser = browser
        browser.stateUpdateHandler = { [weak self] event in
            Task { @MainActor in
                guard let self, self.state.generation == token else { return }
                switch event {
                case .waiting(let error), .failed(let error):
                    self.state.fail("Discovery unavailable. Check Wi-Fi and Local Network permission in Settings, then retry. \(error.localizedDescription)", generation: token)
                    self.endpoints = [:]
                    self.browser?.cancel(); self.browser = nil
                default: break
                }
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            Task { @MainActor in
                guard let self, self.state.generation == token, self.state.searching else { return }
                var sessions: [DiscoveredSession] = []
                var endpoints: [String: NWEndpoint] = [:]
                for result in results {
                    guard case let .service(name, type, domain, _) = result.endpoint else { continue }
                    let session = DiscoveredSession(name: name, type: type, domain: domain)
                    sessions.append(session)
                    endpoints[session.id] = result.endpoint
                }
                self.endpoints = endpoints
                self.state.update(sessions, generation: token)
            }
        }
        browser.start(queue: .main)
    }
    func endpoint(for session: DiscoveredSession) -> NWEndpoint? {
        guard state.searching, state.sessions.contains(session) else { return nil }
        return endpoints[session.id]
    }
    func stop() {
        state.stop()
        browser?.cancel(); browser = nil; endpoints = [:]
    }
}
