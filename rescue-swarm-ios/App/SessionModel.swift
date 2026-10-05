import SwiftUI
import Network
import CryptoKit
import RescueSwarmCore

@MainActor
final class SessionModel: ObservableObject {
    @Published var status = "Choose a role to begin"
    @Published var role = "coordinator"
    @Published var address = ""
    @Published var port = "8765"
    @Published var running = false
    @Published var workerCount = 0
    @Published var completed = 0
    @Published var imageName = "fixture.ppm"
    @Published var imageCount = 1
    @Published var importing = false
    @Published var expectedWorkers = 2
    @Published var policy: TaskLedger.Policy = .nextAvailable
    @Published var failed = 0
    @Published var sessionName = "RescueSwarm-" + String(UUID().uuidString.prefix(6))
    @Published var logs: [String] = []
    @Published var savedReports: [SessionReport] = []
    @Published var reportError: String?
    private var report: SessionReport?
    private var reportStore: ReportStore?
    private var batchBegan: TimeInterval?
    private var image = Data("P6\n2 2\n255\n".utf8) + Data(repeating: 80, count: 12)
    private var batch: ImageBatch?
    private var batchStarted = false
    private var listener: NWListener?
    private var peers: [String: Peer] = [:]
    private var names: [String: String] = [:]
    private var seen: [String: TimeInterval] = [:]
    private var assignedAt: [String: TimeInterval] = [:]
    private var ledger = TaskLedger(count: 0)
    private var timer: Task<Void, Never>?
    private var work: Task<Void, Never>?
    private var generation = UUID()
    private var began: TimeInterval = 0
    private var workerReady = false
    private var workerID = "iphone-" + String(UUID().uuidString.prefix(8))
    private var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    init() {
        do {
            let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                  appropriateFor: nil, create: true)
            reportStore = ReportStore(directory: root.appendingPathComponent("Reports", isDirectory: true))
            refreshReports()
        } catch { reportError = "Report storage unavailable: \(error.localizedDescription)" }
    }
    func reportURL(_ saved: SessionReport) -> URL? { reportStore?.url(for: saved.id) }
    func refreshReports() {
        guard let store = reportStore else { return }
        do {
            var valid: [SessionReport] = []
            var unreadable = 0
            for url in try store.files() {
                do { valid.append(try store.load(url)) } catch { unreadable += 1 }
            }
            savedReports = valid.sorted { $0.started_at > $1.started_at }
            reportError = unreadable == 0 ? nil : "\(unreadable) unreadable report(s) retained in storage."
        } catch { reportError = "Cannot load history: \(error.localizedDescription)" }
    }
    private func checkpoint() throws {
        guard var snapshot = report else { return }
        guard let store = reportStore else { throw CocoaError(.fileWriteUnknown) }
        snapshot.elapsed_s = now - began
        snapshot.batch_s = batchBegan.map { now - $0 }
        snapshot.failed_task_ids = ledger.failed.sorted()
        try store.save(snapshot)
        report = snapshot
    }

    func log(_ text: String) {
        logs.insert(text, at: 0)
        if logs.count > 50 { logs.removeLast() }
    }
    func importImages(_ urls: [URL]) {
        guard !running, !importing else { return }
        importing = true
        Task {
            do {
                let root = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                      appropriateFor: nil, create: true)
                    .appendingPathComponent("ImageBatches", isDirectory: true)
                let imported = try await Task.detached {
                    let access = urls.map { $0.startAccessingSecurityScopedResource() }
                    defer { for (url, granted) in zip(urls, access) where granted { url.stopAccessingSecurityScopedResource() } }
                    return try ImageBatch.copy(urls, into: root)
                }.value
                let old = batch
                batch = imported; imageCount = imported.items.count
                imageName = "\(imageCount) imported images"
                status = "Batch ready. Images copied into app storage."
                if let old { _ = await Task.detached { try? FileManager.default.removeItem(at: old.directory) }.value }
            } catch { status = "Import failed; previous selection retained: \(error.localizedDescription)" }
            importing = false
        }
    }
    func start(discoveredEndpoint: NWEndpoint? = nil) {
        guard !running, !importing else { return }
        let discovered = role == "worker" ? discoveredEndpoint : nil
        guard let number = discovered == nil ? UInt16(port) : UInt16(8765), number > 0,
              let endpoint = NWEndpoint.Port(rawValue: number) else {
            status = "Enter a port between 1 and 65535"; return
        }
        if role == "worker" && discovered == nil && address.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            status = "Enter the coordinator's local IP address"; return
        }
        let advertisedName = sessionName.trimmingCharacters(in: .whitespacesAndNewlines)
        if role == "coordinator" && (advertisedName.isEmpty || advertisedName.utf8.count > 63) {
            status = "Enter a session name of 1–63 UTF-8 bytes"; return
        }
        generation = UUID(); completed = 0; failed = 0; running = true; began = now; batchStarted = false
        batchBegan = nil; report = nil
        status = "Connecting…"
        let session = generation
        if role == "coordinator" {
            ledger = TaskLedger(count: 0)
            report = SessionReport(policy: policy.rawValue,
                imageIDs: batch?.items.map(\.imageID) ?? ["fixture.ppm"],
                expectedWorkers: policy == .single ? 1 : expectedWorkers)
            do { try checkpoint() } catch {
                stop("Cannot start: report could not be saved.", saveReport: false)
                reportError = error.localizedDescription; return
            }
            do {
                let listener = try NWListener(using: .tcp, on: endpoint)
                listener.service = NWListener.Service(name: advertisedName, type: DiscoveryState.serviceType)
                self.listener = listener
                listener.stateUpdateHandler = { [weak self] state in
                    Task { @MainActor in
                        guard let self, self.generation == session else { return }
                        switch state {
                        case .ready: self.status = "Session \(advertisedName) listening on port \(number). Workers can search nearby."
                        case .failed(let error): self.stop("Listener failed: \(error.localizedDescription)")
                        default: break
                        }
                    }
                }
                listener.newConnectionHandler = { [weak self] connection in
                    Task { @MainActor in
                        guard let self, self.generation == session, self.running else { connection.cancel(); return }
                        self.attach(Peer(connection), session: session)
                    }
                }
                listener.start(queue: .main)
            } catch { stop("Cannot listen: \(error.localizedDescription)"); return }
        } else {
            let target = discovered ?? .hostPort(host: NWEndpoint.Host(address.trimmingCharacters(in: .whitespacesAndNewlines)), port: endpoint)
            attach(Peer(NWConnection(to: target, using: .tcp)), session: session)
        }
        timer = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 200_000_000)
                guard !Task.isCancelled, let self, self.generation == session else { return }
                self.tick()
            }
        }
    }
    private func attach(_ peer: Peer, session: UUID) {
        // Keep the first milestone bounded even if many connections arrive.
        guard peers.count < 8 else { peer.close("Session full"); return }
        peers[peer.id] = peer; seen[peer.id] = now
        peer.onReady = { [weak self, weak peer] in
            guard let self, let peer, self.generation == session else { return }
            if self.role == "worker" {
                var hello = Message(type: "hello"); hello.version = 1; hello.worker_id = String(self.workerID)
                peer.send(Frame(hello)); self.workerReady = true
                self.status = "Connected. Waiting for an image."
            }
        }
        peer.onFrame = { [weak self, weak peer] frame in
            guard let self, let peer, self.generation == session else { return }
            self.seen[peer.id] = self.now
            self.handle(frame, peer: peer, session: session)
        }
        let peerID = peer.id
        peer.onClose = { [weak self] reason in
            guard let self, self.generation == session else { return }
            self.peers.removeValue(forKey: peerID)
            let name = self.names.removeValue(forKey: peerID)
            self.seen.removeValue(forKey: peerID)
            self.assignedAt.removeValue(forKey: peerID)
            if let name { self.ledger.disconnect(name) }
            self.workerCount = self.names.count
            self.log(reason)
            if self.role == "worker" { self.stop("Disconnected. Tap Start to reconnect.") }
            else { self.dispatch() }
        }
        peer.start()
    }
    private func handle(_ frame: Frame, peer: Peer, session: UUID) {
        let m = frame.message
        if role == "coordinator" {
            guard frame.payload.isEmpty else { peer.close("Unexpected worker payload"); return }
            if names[peer.id] == nil {
                guard m.type == "hello", m.version == 1, let name = m.worker_id,
                      !name.isEmpty, name.count <= 64, !names.values.contains(name) else {
                    peer.close("Invalid hello or duplicate worker ID"); return
                }
                if policy == .single && !names.isEmpty { peer.close("Single-worker mode already has a worker"); return }
                names[peer.id] = name; workerCount = names.count; log("Joined: \(name)"); dispatch(); return
            }
            if m.type == "heartbeat" { return }
            do {
                guard m.type == "result" else { throw WireError.invalidResult }
                guard let name = names[peer.id], let a = ledger.active[name] else { log("Ignored result without active assignment"); return }
                var updatedLedger = ledger
                if try updatedLedger.accept(m, from: name, imageID: imageID(a.task)) {
                    // Validate first; persist before acknowledging completion in memory/UI.
                    do {
                        try report?.append(SavedResult(workerID: name, receivedSeconds: now - began, result: m))
                        try checkpoint()
                    } catch {
                        stop("Stopped: result could not be saved.", saveReport: false)
                        reportError = error.localizedDescription; return
                    }
                    ledger = updatedLedger
                    assignedAt.removeValue(forKey: peer.id)
                    completed = ledger.completed.count
                    log("Accepted task \(m.task_id ?? -1), attempt \(m.attempt_id ?? -1), detector: \(m.detector ?? "unknown")")
                    dispatch()
                } else { log("Ignored duplicate or old result") }
            } catch { peer.close("Invalid or failed result; reassignment requested") }
        } else {
            guard m.type == "task", let task = m.task_id, task >= 0,
                  let attempt = m.attempt_id, attempt > 0, let imageID = m.image_id,
                  !imageID.isEmpty, !frame.payload.isEmpty,
                  m.sha256 == Self.hash(frame.payload), work == nil else {
                peer.close("Invalid task, checksum mismatch, or overlapping assignment"); return
            }
            status = "Received \(imageID): \(frame.payload.count) bytes. Mock processing…"
            let started = now
            work = Task { [weak self, weak peer] in
                do { try await Task.sleep(nanoseconds: 150_000_000) } catch { return }
                guard let self, let peer, self.generation == session else { return }
                var result = Message(type: "result")
                result.task_id = task; result.attempt_id = attempt; result.image_id = imageID
                result.status = "success"; result.processing_ms = (self.now - started) * 1000
                result.detections = []; result.synthetic = true; result.detector = "mock"
                peer.send(Frame(result)); self.completed += 1
                self.status = "Mock result submitted. No person detection performed."
                self.log("Verified image hash; submitted task \(task), attempt \(attempt)")
                self.work = nil
            }
        }
    }
    private func dispatch() {
        guard running, role == "coordinator" else { return }
        if !batchStarted {
            let required = policy == .single ? 1 : expectedWorkers
            guard names.count >= required else { status = "Waiting for workers: \(names.count)/\(required)"; return }
            ledger = TaskLedger(count: imageCount, policy: policy, roster: Array(names.values))
            batchStarted = true
            batchBegan = now
        }
        failed = ledger.failed.count
        if ledger.finished {
            stop("Batch finished: \(ledger.completed.count) accepted, \(ledger.failed.count) failed.")
            return
        }
        for id in names.keys.sorted() {
            guard let peer = peers[id], let name = names[id],
                  let a = ledger.assign(to: name, connected: Set(names.values)) else { continue }
            let session = generation
            let selected = batch
            let fixture = image
            let filename = imageID(a.task)
            assignedAt[id] = now
            report?.assignments += 1
            if a.attempt > 1 { report?.retries += 1 }
            Task {
                do {
                    let (bytes, hash) = try await Task.detached {
                        let bytes = try selected?.read(a.task) ?? fixture
                        return (bytes, Self.hash(bytes))
                    }.value
                    guard generation == session, peers[id] != nil, ledger.active[name] == a else { return }
                    var m = Message(type: "task")
                    m.task_id = a.task; m.attempt_id = a.attempt; m.image_id = filename; m.sha256 = hash
                    report?.image_bytes_submitted += bytes.count
                    peer.send(Frame(m, payload: bytes))
                    status = "Processing batch: \(completed)/\(imageCount) accepted"
                } catch {
                    guard generation == session, peers[id] != nil, ledger.active[name] == a else { return }
                    peer.close("Image read failed: \(error.localizedDescription)")
                }
            }
        }
    }
    private func tick() {
        if now - began > 600 { stop("10-minute session limit reached. Start a new test session."); return }
        if role == "worker" && workerReady {
            for peer in peers.values { peer.send(Frame(Message(type: "heartbeat"))) }
        } else {
            for (id, peer) in Array(peers) {
                if now - (seen[id] ?? now) > 3 || now - (assignedAt[id] ?? now) > 10 {
                    peer.close("Heartbeat or task deadline expired")
                }
            }
        }
    }
    func stop(_ message: String = "Stopped", saveReport: Bool = true) {
        var savingError: String?
        if running, report != nil, saveReport {
            report?.state = batchStarted && ledger.finished ? "finished" : "stopped"
            report?.stop_reason = message
            do { try checkpoint() } catch { savingError = "Final report save failed: \(error.localizedDescription)" }
        }
        generation = UUID(); running = false; workerReady = false
        timer?.cancel(); timer = nil; work?.cancel(); work = nil
        listener?.cancel(); listener = nil
        for peer in peers.values { peer.close() }
        peers.removeAll(); names.removeAll(); seen.removeAll(); assignedAt.removeAll(); workerCount = 0
        status = message
        refreshReports()
        if let savingError { reportError = savingError }
    }
    private func imageID(_ task: Int) -> String {
        batch?.items[task].imageID ?? "fixture.ppm"
    }
    nonisolated private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
