import Foundation
import Network
import RescueSwarmCore

@MainActor
final class Peer {
    let id = UUID().uuidString
    private let connection: NWConnection
    private var decoder = FrameDecoder()
    private var closed = false
    var onReady: (() -> Void)?
    var onFrame: ((Frame) -> Void)?
    var onClose: ((String) -> Void)?

    init(_ connection: NWConnection) { self.connection = connection }
    func start() {
        connection.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                guard let self, !self.closed else { return }
                switch state {
                case .ready: self.onReady?(); self.receive()
                case .failed(let error): self.close(error.localizedDescription)
                case .waiting(let error): self.close("Connection unavailable: \(error.localizedDescription)")
                default: break
                }
            }
        }
        connection.start(queue: .main)
    }
    func send(_ frame: Frame) {
        guard !closed else { return }
        do {
            // A whole frame is submitted in one ordered send on the main actor.
            connection.send(content: try Wire.encode(frame), completion: .contentProcessed { [weak self] error in
                if let error { Task { @MainActor in self?.close(error.localizedDescription) } }
            })
        } catch { close("Encoding failed: \(error)") }
    }
    private func receive() {
        guard !closed else { return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, ended, error in
            Task { @MainActor in
                guard let self, !self.closed else { return }
                do {
                    if let data {
                        for frame in try self.decoder.append(data) {
                            guard !self.closed else { return }
                            self.onFrame?(frame)
                        }
                    }
                    if let error { self.close(error.localizedDescription) }
                    else if ended { self.close(self.decoder.hasIncompleteFrame ? "Truncated frame" : "Peer disconnected") }
                    else { self.receive() }
                } catch { self.close("Invalid frame: \(error)") }
            }
        }
    }
    func close(_ reason: String = "Stopped") {
        guard !closed else { return }
        closed = true
        connection.cancel()
        onClose?(reason)
    }
}
