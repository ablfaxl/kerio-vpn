import SwiftUI
import AppKit
import Foundation

private enum KerioPaths {
    static let daemon = "/usr/local/kerio/vpnclient/kvpncsvc"
    static let statusBundle = "/usr/local/kerio/vpnclient/KVpnClientStatus.app"
    static let statusExecutable = statusBundle + "/Contents/MacOS/KVpnClientStatus"
    static let nativeConfig = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".kerio/vpnclient/user.cfg")
    static let userLogs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".kerio/vpnclient/logs")
    static let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/KerioVPNMac")
    static let profiles = support.appendingPathComponent("profiles.json")
    static let isolatedHome = support.appendingPathComponent("KerioHome")
    static let isolatedConfig = isolatedHome.appendingPathComponent(".kerio/vpnclient/user.cfg")
    static let isolatedPID = support.appendingPathComponent("isolated-client.pid")
}

struct VPNProfile: Identifiable, Codable, Equatable {
    var id = UUID()
    var name: String
    var server: String
    var username: String
    var persistent = false
}

@MainActor
final class KerioModel: ObservableObject {
    @Published var installed = false
    @Published var serviceRunning = false
    @Published var connected = false
    @Published var status = "Checking…"
    @Published var profiles: [VPNProfile] = []
    @Published var selectedID: UUID?
    @Published var recentLog = ""
    @Published var errorMessage: String?
    @Published var isolatedClientRunning = false
    private var isolatedClient: Process?

    init() { loadProfiles() }
    var selectedProfile: VPNProfile? { profiles.first { $0.id == selectedID } }

    func refresh() {
        installed = FileManager.default.isExecutableFile(atPath: KerioPaths.daemon)
        guard installed else {
            status = "Official Kerio client is required"; serviceRunning = false; connected = false
            return
        }
        let result = Self.run("/bin/launchctl", ["print", "system/com.kerio.kvpncsvc"])
        serviceRunning = result.code == 0 && result.output.contains("state = running")
        readLog()
        let statuses = recentLog.split(separator: "\n").filter { $0.contains("received status packet") }
        connected = statuses.last?.contains("status packet (connected,") == true
        status = connected ? "Connected" : (serviceRunning ? "Ready" : "Service stopped")
        isolatedClientRunning = isolatedRunningApplication() != nil
    }

    func add(_ profile: VPNProfile) {
        profiles.append(profile); selectedID = profile.id; saveProfiles()
    }

    func removeSelected() {
        guard let selectedID else { return }
        profiles.removeAll { $0.id == selectedID }
        self.selectedID = profiles.first?.id
        saveProfiles()
    }

    func importExisting() {
        let existing = ConnectionXMLDelegate.read(KerioPaths.nativeConfig)
        var imported = 0
        for item in existing where !profiles.contains(where: {
            $0.server.caseInsensitiveCompare(item.server) == .orderedSame && $0.username == item.username
        }) {
            profiles.append(item); imported += 1
        }
        selectedID = selectedID ?? profiles.first?.id
        saveProfiles()
        status = imported == 0 ? "No new connections to import" : "Imported \(imported) connection(s)"
    }

    func launchIsolatedClient() {
        guard installed else {
            NSWorkspace.shared.open(URL(string: "https://www.gfi.com/products-and-solutions/network-security-solutions/keriocontrol/resources/vpn")!)
            return
        }
        do {
            if let running = isolatedRunningApplication() {
                running.activate(options: [])
                isolatedClientRunning = true
                status = "Isolated Kerio client is already open"
                return
            }
            try writeIsolatedConfiguration()
            let process = Process()
            process.executableURL = URL(fileURLWithPath: KerioPaths.statusExecutable)
            process.currentDirectoryURL = URL(fileURLWithPath: KerioPaths.statusBundle)
            var environment = ProcessInfo.processInfo.environment
            environment["HOME"] = KerioPaths.isolatedHome.path
            process.environment = environment
            try process.run()
            isolatedClient = process
            try String(process.processIdentifier).write(to: KerioPaths.isolatedPID,
                                                        atomically: true, encoding: .utf8)
            isolatedClientRunning = true
            status = "Isolated Kerio client opened"
        } catch { errorMessage = error.localizedDescription }
    }

    func stopIsolatedClient() {
        guard let running = isolatedRunningApplication() else {
            try? FileManager.default.removeItem(at: KerioPaths.isolatedPID)
            isolatedClientRunning = false
            status = "Kerio helper is already hidden"
            return
        }
        if running.terminate() {
            try? FileManager.default.removeItem(at: KerioPaths.isolatedPID)
            isolatedClient = nil
            isolatedClientRunning = false
            status = connected ? "Connected" : "Kerio helper hidden"
        } else {
            errorMessage = "Could not close the isolated Kerio helper."
        }
    }

    func openLogs() {
        try? FileManager.default.createDirectory(at: KerioPaths.userLogs, withIntermediateDirectories: true)
        NSWorkspace.shared.open(KerioPaths.userLogs)
    }

    private func loadProfiles() {
        guard let data = try? Data(contentsOf: KerioPaths.profiles),
              let saved = try? JSONDecoder().decode([VPNProfile].self, from: data) else { return }
        profiles = saved; selectedID = saved.first?.id
    }

    private func saveProfiles() {
        do {
            try FileManager.default.createDirectory(at: KerioPaths.support, withIntermediateDirectories: true)
            let data = try JSONEncoder.pretty.encode(profiles)
            try data.write(to: KerioPaths.profiles, options: [.atomic])
            try writeIsolatedConfiguration()
        } catch { errorMessage = error.localizedDescription }
    }

    private func writeIsolatedConfiguration() throws {
        let directory = KerioPaths.isolatedConfig.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let connections = profiles.map { profile in
            """
                <connection type="user">
                  <description>\(profile.name.xmlEscaped)</description>
                  <server>\(profile.server.xmlEscaped)</server>
                  <username>\(profile.username.xmlEscaped)</username>
                  <password></password>
                  <savePassword>0</savePassword>
                  <persistent>\(profile.persistent ? 1 : 0)</persistent>
                </connection>
            """
        }.joined(separator: "\n")
        let xml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <config>
          <connections>
        \(connections)
          </connections>
          <application><showStatus>0</showStatus><language/></application>
        </config>
        """
        try xml.data(using: .utf8)!.write(to: KerioPaths.isolatedConfig, options: [.atomic])
    }

    private func isolatedRunningApplication() -> NSRunningApplication? {
        guard let raw = try? String(contentsOf: KerioPaths.isolatedPID, encoding: .utf8),
              let pid = pid_t(raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated else {
            return nil
        }
        return app
    }

    private func readLog() {
        let candidates = [KerioPaths.userLogs.appendingPathComponent("debug.log"),
                          URL(fileURLWithPath: "/usr/local/kerio/vpnclient/logs/debug.log")]
        guard let data = candidates.compactMap({ try? Data(contentsOf: $0) }).first else {
            recentLog = "No readable debug log found."; return
        }
        recentLog = String(decoding: data.suffix(72 * 1024), as: UTF8.self)
            .split(separator: "\n", omittingEmptySubsequences: true).suffix(80).joined(separator: "\n")
    }

    private static func run(_ executable: String, _ arguments: [String]) -> (code: Int32, output: String) {
        let process = Process(); let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable); process.arguments = arguments
        process.standardOutput = pipe; process.standardError = pipe
        do { try process.run(); process.waitUntilExit() } catch { return (127, error.localizedDescription) }
        return (process.terminationStatus, String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self))
    }
}

private final class ConnectionXMLDelegate: NSObject, XMLParserDelegate {
    var profiles: [VPNProfile] = []
    private var inConnection = false
    private var field = ""
    private var values: [String: String] = [:]

    static func read(_ url: URL) -> [VPNProfile] {
        guard let parser = XMLParser(contentsOf: url) else { return [] }
        let delegate = ConnectionXMLDelegate(); parser.delegate = delegate
        return parser.parse() ? delegate.profiles : []
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
                qualifiedName qName: String?, attributes attributeDict: [String: String] = [:]) {
        if elementName == "connection" { inConnection = true; values = [:] }
        field = inConnection ? elementName : ""
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        guard inConnection, field != "password" else { return }
        values[field, default: ""] += string
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName qName: String?) {
        if elementName == "connection" {
            let server = clean("server")
            if !server.isEmpty {
                profiles.append(.init(name: clean("description").isEmpty ? server : clean("description"),
                                      server: server, username: clean("username"),
                                      persistent: clean("persistent") == "1"))
            }
            inConnection = false
        }
        field = ""
    }

    private func clean(_ key: String) -> String {
        values[key, default: ""].trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private extension JSONEncoder {
    static var pretty: JSONEncoder { let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]; return encoder }
}

private extension String {
    var xmlEscaped: String {
        replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&apos;")
    }
}

struct AddProfileView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""; @State private var server = ""; @State private var username = ""
    @State private var persistent = false
    let onAdd: (VPNProfile) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("New connection").font(.title2).bold()
            Form {
                TextField("Name", text: $name)
                TextField("Server (host or host:port)", text: $server)
                TextField("Username", text: $username)
                Toggle("Persistent connection", isOn: $persistent)
            }
            HStack { Spacer(); Button("Cancel") { dismiss() }; Button("Add") {
                onAdd(.init(name: name.trimmingCharacters(in: .whitespaces).isEmpty ? server : name,
                            server: server.trimmingCharacters(in: .whitespaces),
                            username: username.trimmingCharacters(in: .whitespaces), persistent: persistent)); dismiss()
            }.buttonStyle(.borderedProminent).disabled(server.trimmingCharacters(in: .whitespaces).isEmpty) }
        }.padding(24).frame(width: 430)
    }
}

struct ContentView: View {
    @StateObject private var model = KerioModel()
    @State private var showingAdd = false

    var body: some View {
        NavigationSplitView {
            List(selection: $model.selectedID) {
                ForEach(model.profiles) { profile in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(profile.name).font(.headline)
                        Text("\(profile.username) @ \(profile.server)").font(.caption).foregroundStyle(.secondary)
                    }.padding(.vertical, 5).tag(profile.id)
                }
            }
            .overlay { if model.profiles.isEmpty { ContentUnavailableView("No connections", systemImage: "network.badge.shield.half.filled", description: Text("Add a connection or import your existing Kerio setup.")) } }
            .navigationTitle("Connections")
            .toolbar {
                ToolbarItemGroup {
                    Button { showingAdd = true } label: { Label("Add", systemImage: "plus") }
                    Button { model.removeSelected() } label: { Label("Remove", systemImage: "minus") }.disabled(model.selectedID == nil)
                }
            }
        } detail: {
            ZStack {
                LinearGradient(colors: [Color(nsColor: .windowBackgroundColor), .blue.opacity(0.06)], startPoint: .top, endPoint: .bottom).ignoresSafeArea()
                VStack(alignment: .leading, spacing: 22) {
                    HStack(spacing: 12) {
                        Image(systemName: model.connected ? "checkmark.shield.fill" : "shield.lefthalf.filled")
                            .font(.system(size: 30)).foregroundStyle(model.connected ? .green : .blue)
                        VStack(alignment: .leading) { Text(model.status).font(.title2).bold(); Text("Independent profile workspace").foregroundStyle(.secondary) }
                        Spacer(); Button("Refresh") { model.refresh() }
                    }
                    if let profile = model.selectedProfile {
                        GroupBox {
                            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 9) {
                                GridRow { Text("Connection").foregroundStyle(.secondary); Text(profile.name).bold() }
                                GridRow { Text("Server").foregroundStyle(.secondary); Text(profile.server).textSelection(.enabled) }
                                GridRow { Text("Username").foregroundStyle(.secondary); Text(profile.username).textSelection(.enabled) }
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(4)
                        }
                    }
                    HStack {
                        Button(model.isolatedClientRunning ? "Show Kerio helper" : "Open isolated Kerio client") {
                            model.launchIsolatedClient()
                        }.buttonStyle(.borderedProminent).disabled(!model.installed || model.profiles.isEmpty)
                        if model.isolatedClientRunning {
                            Button("Hide Kerio helper") { model.stopIsolatedClient() }
                        }
                        Button("Add connection") { showingAdd = true }
                        Button("Import existing") { model.importExisting() }
                        Button("Logs") { model.openLogs() }.disabled(!model.installed)
                    }
                    GroupBox("Recent activity") {
                        ScrollView { Text(model.recentLog).font(.system(.caption, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(minHeight: 210)
                    }
                    Text("Profiles are stored separately in Application Support. Your existing ~/.kerio configuration is never modified.")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(26)
            }
        }
        .frame(minWidth: 860, minHeight: 560)
        .sheet(isPresented: $showingAdd) { AddProfileView(onAdd: model.add) }
        .alert("Kerio VPN", isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })) {
            Button("OK") { model.errorMessage = nil }
        } message: { Text(model.errorMessage ?? "") }
        .task { model.refresh() }
    }
}

@main struct KerioVPNMacApp: App {
    var body: some Scene { WindowGroup { ContentView() }; Settings { Text("Kerio VPN for macOS") } }
}
