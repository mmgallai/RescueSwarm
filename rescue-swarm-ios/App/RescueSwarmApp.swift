import SwiftUI
import UniformTypeIdentifiers
import RescueSwarmCore

@main
@MainActor
struct RescueSwarmApp: App {
    @StateObject private var model = SessionModel()
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
                .onChange(of: scenePhase) { phase in
                    if phase == .background && model.running {
                        model.stop("Session stopped when app entered background. Reopen and start again.")
                    }
                }
        }
    }
}

@MainActor
struct ContentView: View {
    @ObservedObject var model: SessionModel
    @StateObject private var discovery = SessionDiscovery()
    @Environment(\.scenePhase) private var scenePhase
    @State private var importing = false
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Batch test • mock processing", systemImage: "testtube.2")
                    Text("Distribute images over local Wi-Fi. This build does not detect people or send TAK alerts.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Your role") {
                    Picker("Role", selection: $model.role) {
                        Text("Coordinator").tag("coordinator")
                        Text("Worker").tag("worker")
                    }.pickerStyle(.segmented)
                    if model.role == "worker" {
                        Button(discovery.state.searching ? "Refresh nearby sessions" : "Find nearby sessions") { discovery.start() }
                        if let problem = discovery.state.problem { Text(problem).foregroundStyle(.red) }
                        if discovery.state.searching && discovery.state.sessions.isEmpty {
                            Text("Searching… Start a coordinator on the same local Wi-Fi. You can also connect manually below.").font(.footnote)
                        }
                        ForEach(discovery.state.sessions) { session in
                            Button {
                                guard let endpoint = discovery.endpoint(for: session) else {
                                    model.status = "Session disappeared. Search again."; return
                                }
                                discovery.stop()
                                model.start(discoveredEndpoint: endpoint)
                            } label: {
                                Label("Join \(session.name)", systemImage: "wifi")
                            }
                        }
                        if discovery.state.searching { Button("Stop searching") { discovery.stop() } }
                        TextField("Coordinator IP address", text: $model.address)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                    TextField("Port", text: $model.port).keyboardType(.numberPad)
                    if model.role == "coordinator" {
                        TextField("Session name", text: $model.sessionName)
                        LabeledContent("Image", value: model.imageName)
                        Button("Choose images") { importing = true }
                        Picker("Scheduling", selection: $model.policy) {
                            Text("Next available").tag(TaskLedger.Policy.nextAvailable)
                            Text("Round robin").tag(TaskLedger.Policy.roundRobin)
                            Text("Single worker").tag(TaskLedger.Policy.single)
                        }
                        if model.policy != .single { Stepper("Wait for \(model.expectedWorkers) workers", value: $model.expectedWorkers, in: 1...8) }
                        Text("Workers can find this session nearby. If discovery is unavailable, share this iPhone’s Wi-Fi IP address from Settings.")
                            .font(.footnote)
                    }
                }.disabled(model.running || model.importing)
                Section("Session") {
                    Text(model.status).accessibilityLabel("Session status: \(model.status)")
                    LabeledContent("Connected workers", value: String(model.workerCount))
                    LabeledContent("Results", value: String(model.completed))
                    if model.role == "coordinator" { LabeledContent("Failed", value: String(model.failed)) }
                    if model.running { Button("Stop", role: .destructive) { model.stop() } }
                    else { Button(model.importing ? "Importing…" : "Start") { model.start() }.disabled(model.importing) }
                }
                Section("Saved coordinator runs") {
                    if let error = model.reportError { Text(error).foregroundStyle(.red) }
                    if model.savedReports.isEmpty { Text("No saved runs yet").foregroundStyle(.secondary) }
                    ForEach(model.savedReports) { report in
                        VStack(alignment: .leading) {
                            Text("\(report.policy) • \(report.results.count)/\(report.image_ids.count) results")
                            Text(report.state == "running" ? "Unfinished checkpoint" : report.state).font(.caption)
                            Text(report.started_at, style: .date).font(.caption)
                            if let url = model.reportURL(report) { ShareLink("Export JSON report", item: url) }
                        }
                    }
                    Button("Refresh history") { model.refreshReports() }.disabled(model.running)
                }
                Section("Recent events") {
                    if model.logs.isEmpty { Text("No events yet").foregroundStyle(.secondary) }
                    ForEach(Array(model.logs.enumerated()), id: \.offset) { _, event in Text(event).font(.caption) }
                }
            }
            .navigationTitle("RescueSwarm")
            .onChange(of: model.role) { _ in discovery.stop() }
            .onChange(of: model.running) { running in if running { discovery.stop() } }
            .onChange(of: scenePhase) { phase in if phase != .active { discovery.stop() } }
            .onDisappear { discovery.stop() }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.jpeg, .png], allowsMultipleSelection: true) { result in
                switch result {
                case .success(let urls): model.importImages(urls)
                case .failure(let error): model.status = "Import failed: \(error.localizedDescription)"
                }
            }
        }
    }
}
