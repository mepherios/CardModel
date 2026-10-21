// Cardmodel Arcade: the launcher. A native window around the arcade's pages (served by `cardmodel arcade serve`,
// which this app starts if it is not running), and the client that does what a page cannot: download a
// build's chunks, check every SHA-256, assemble and install the files, reuse unchanged chunks on an update,
// verify an installation, launch a game and keep its play time, read its achievements from its save.
//
// Everything lives in ~/Library/Application Support/Cardmodel Arcade: library/ (installed games),
// saves/ (each game's save, written by the game), launcher.json (what is installed, play time, settings).
// The user's own cartridges are played by an installed console player (a system build): it is started with
// --rom on the cartridge where it is, and a save folder per cartridge.

import AppKit
import CryptoKit
import WebKit

let port = 8770
let base = URL(string: "http://127.0.0.1:\(port)")!
let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    .appendingPathComponent("Cardmodel Arcade", isDirectory: true)
let libraryDir = support.appendingPathComponent("library", isDirectory: true)
let savesDir = support.appendingPathComponent("saves", isDirectory: true)
let stateFile = support.appendingPathComponent("launcher.json")

struct Installed: Codable {
    var version: String
    var build: String
    var size: Int
    var installedAt: Double
    var playSeconds: Double
    var lastPlayed: Double
    var app: String
    var executable: String
    var manifest: String
}

struct Settings: Codable {
    var bandwidth: Int = 0
    var user: String = NSFullUserName()
}

struct Played: Codable {
    var playSeconds: Double
    var lastPlayed: Double
}

struct LauncherState: Codable {
    var library: [String: Installed] = [:]
    var settings = Settings()
    var played: [String: Played]? = [:]     // cartridges, by id
}

struct FileEntry: Codable {
    struct Chunk: Codable { let sha256: String; let size: Int }
    let path: String
    let size: Int
    let sha256: String
    let executable: Bool
    let chunks: [Chunk]
}

struct Manifest: Codable {
    let id: String
    let title: String
    let version: String
    let build: String
    let app: String
    let executable: String
    let size: Int
    let files: [FileEntry]
}

enum ArcadeError: Error, CustomStringConvertible {
    case message(String)
    var description: String { if case .message(let m) = self { return m }; return "error" }
}

func sha256(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

final class Arcade: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var state = LauncherState()
    var server: Process?
    var running: [String: (Process, Double)] = [:]
    var download: Task<Void, Never>?
    var downloadId: String?
    var paused = false
    var cancelled = false

    // -- start ---------------------------------------------------------------------------------------------------------
    func applicationDidFinishLaunching(_ n: Notification) {
        try? FileManager.default.createDirectory(at: libraryDir, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(at: savesDir, withIntermediateDirectories: true)
        load()
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "arcade")
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 880),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Cardmodel Arcade"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = NSColor(red: 0.09, green: 0.10, blue: 0.13, alpha: 1)
        window.minSize = NSSize(width: 1040, height: 680)
        window.contentView = web
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("CardmodelArcade")
        window.makeKeyAndOrderFront(nil)
        menu()
        NSApp.activate(ignoringOtherApps: true)
        showSplash("Starting the arcade service…")
        Task { await self.connect() }
    }

    func menu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let m = NSMenu()
        m.addItem(withTitle: "About Cardmodel Arcade", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        m.addItem(NSMenuItem.separator())
        m.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        m.addItem(withTitle: "Quit Cardmodel Arcade", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = m
        let editItem = NSMenuItem()
        main.addItem(editItem)
        let e = NSMenu(title: "Edit")
        e.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        e.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        e.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = e
        NSApp.mainMenu = main
    }

    @objc func reload() { web.reload() }

    func showSplash(_ text: String) {
        let html = """
        <html><body style="margin:0;background:#171a21;color:#c7d5e0;font:15px -apple-system,Helvetica;display:flex;
        align-items:center;justify-content:center;height:100vh;flex-direction:column">
        <div style="font-size:30px;letter-spacing:6px;color:#fff;margin-bottom:14px">CARDMODEL ARCADE</div>
        <div>\(text)</div></body></html>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    func alive() async -> Bool {
        var req = URLRequest(url: base.appendingPathComponent("api/status"))
        req.timeoutInterval = 1.5
        if let (_, resp) = try? await URLSession.shared.data(for: req), let h = resp as? HTTPURLResponse { return h.statusCode == 200 }
        return false
    }

    func connect() async {
        if !(await alive()) {
            let home = Bundle.main.object(forInfoDictionaryKey: "CardmodelHome") as? String ?? ""
            let python = Bundle.main.object(forInfoDictionaryKey: "CardmodelPython") as? String ?? ""
            let p = Process()
            if FileManager.default.isExecutableFile(atPath: python) {
                p.executableURL = URL(fileURLWithPath: python)
                p.arguments = ["-B", home + "/bin/cardmodel", "arcade", "serve", "--port", "\(port)"]
            } else {
                p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                p.arguments = ["python3", "-B", home + "/bin/cardmodel", "arcade", "serve", "--port", "\(port)"]
            }
            p.currentDirectoryURL = URL(fileURLWithPath: home)
            p.standardOutput = FileHandle.nullDevice
            p.standardError = FileHandle.nullDevice
            do { try p.run(); server = p } catch {
                await MainActor.run { self.showSplash("Could not start the arcade service: \(error)") }
                return
            }
            for _ in 0..<100 {
                if await alive() { break }
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
        }
        await MainActor.run {
            self.web.load(URLRequest(url: base.appendingPathComponent("ui/index.html")))
        }
    }

    // the page could not load (the service restarting): show the splash and connect again
    func webView(_ w: WKWebView, didFailProvisionalNavigation nav: WKNavigation!, withError error: Error) { retry() }
    func webView(_ w: WKWebView, didFail nav: WKNavigation!, withError error: Error) { retry() }
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { retry() }
    func retry() {
        showSplash("Reconnecting to the arcade service…")
        Task {
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            await self.connect()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ n: Notification) {
        save()
        server?.terminate()
    }

    // -- state -----------------------------------------------------------------------------------------------------
    func load() {
        if let d = try? Data(contentsOf: stateFile), let s = try? JSONDecoder().decode(LauncherState.self, from: d) { state = s }
    }
    func save() {
        if let d = try? JSONEncoder().encode(state) { try? d.write(to: stateFile, options: .atomic) }
    }
    func installDir(_ id: String) -> URL { libraryDir.appendingPathComponent(id, isDirectory: true) }

    func snapshot() -> [String: Any] {
        var lib: [String: Any] = [:]
        for (id, g) in state.library {
            lib[id] = ["version": g.version, "build": g.build, "size": g.size, "installedAt": g.installedAt,
                       "playSeconds": g.playSeconds + (running[id].map { Date().timeIntervalSince1970 - $0.1 } ?? 0),
                       "lastPlayed": g.lastPlayed, "running": running[id] != nil,
                       "achievements": achievements(id)]
        }
        var carts: [String: Any] = [:]
        for (id, c) in state.played ?? [:] {
            carts[id] = ["playSeconds": c.playSeconds + (running[id].map { Date().timeIntervalSince1970 - $0.1 } ?? 0),
                         "lastPlayed": c.lastPlayed, "running": running[id] != nil]
        }
        for id in running.keys where state.library[id] == nil && carts[id] == nil {
            carts[id] = ["playSeconds": 0, "lastPlayed": Date().timeIntervalSince1970, "running": true]
        }
        return ["library": lib, "played": carts, "settings": ["bandwidth": state.settings.bandwidth, "user": state.settings.user],
                "downloading": downloadId as Any, "paused": paused, "native": true,
                "libraryPath": libraryDir.path]
    }

    func achievements(_ id: String) -> [Int] {
        let f = savesDir.appendingPathComponent(id).appendingPathComponent("save.bin")
        guard let d = try? Data(contentsOf: f), d.count > 48 else { return [] }
        return (32..<48).map { Int(d[$0]) }
    }

    // -- the page talks to us -------------------------------------------------------------------------------------
    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let cmd = body["cmd"] as? String else { return }
        let id = body["id"] as? String ?? ""
        switch cmd {
        case "state": emit(["type": "state", "state": snapshot()])
        case "install", "update": startDownload(id)
        case "pause": paused = true; emit(["type": "state", "state": snapshot()])
        case "resume": paused = false; emit(["type": "state", "state": snapshot()])
        case "cancel": cancelled = true; paused = false
        case "play": play(id)
        case "play_rom":
            playRom(id, player: body["player"] as? String ?? "", path: body["path"] as? String ?? "",
                    title: body["title"] as? String ?? "")
        case "pick_folder":
            let panel = NSOpenPanel()
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.allowsMultipleSelection = false
            panel.prompt = "Use This Folder"
            panel.message = "A folder with cartridges (they are played where they are, never copied)"
            panel.beginSheetModal(for: window) { [weak self] r in
                guard r == .OK, let url = panel.url else { return }
                self?.emit(["type": "folder", "system": body["system"] as? String ?? "", "path": url.path])
            }
        case "reveal_rom":
            if let path = body["path"] as? String { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)]) }
        case "stop": running[id]?.0.terminate()
        case "verify": verify(id)
        case "uninstall": uninstall(id)
        case "reveal":
            NSWorkspace.shared.activateFileViewerSelecting([installDir(id)])
        case "settings":
            if let b = body["bandwidth"] as? Int { state.settings.bandwidth = b }
            save()
            emit(["type": "state", "state": snapshot()])
        default: break
        }
    }

    func emit(_ obj: [String: Any]) {
        guard let d = try? JSONSerialization.data(withJSONObject: obj), let s = String(data: d, encoding: .utf8) else { return }
        DispatchQueue.main.async { self.web.evaluateJavaScript("window.arcade && window.arcade.event(\(s))") }
    }

    func progress(_ id: String, _ phase: String, _ done: Int, _ total: Int, _ rate: Double, _ label: String = "") {
        emit(["type": "progress", "id": id, "phase": phase, "done": done, "total": total, "rate": rate, "label": label])
    }

    // -- downloads ---------------------------------------------------------------------------------------------------
    func fetchJSON(_ path: String) async throws -> Any {
        let (d, r) = try await URLSession.shared.data(from: base.appendingPathComponent(path))
        guard (r as? HTTPURLResponse)?.statusCode == 200 else { throw ArcadeError.message("\(path): \((r as? HTTPURLResponse)?.statusCode ?? 0)") }
        return try JSONSerialization.jsonObject(with: d)
    }

    func startDownload(_ id: String) {
        if download != nil { return }
        downloadId = id
        paused = false
        cancelled = false
        emit(["type": "state", "state": snapshot()])
        download = Task {
            do {
                try await self.install(id)
                self.emit(["type": "done", "id": id])
            } catch {
                self.emit(["type": "error", "id": id, "message": "\(error)"])
            }
            self.download = nil
            self.downloadId = nil
            self.emit(["type": "state", "state": self.snapshot()])
        }
    }

    // build on the service if the cards changed since its last build, then download what is not here yet
    func install(_ id: String) async throws {
        progress(id, "preparing", 0, 1, 0, "asking the arcade service")
        guard var entry = try await fetchJSON("api/game/\(id)") as? [String: Any] else { throw ArcadeError.message("no game") }
        if (entry["build_due"] as? Bool) == true {
            let req = { () -> URLRequest in
                var r = URLRequest(url: base.appendingPathComponent("api/build/\(id)")); r.httpMethod = "POST"; return r }()
            _ = try await URLSession.shared.data(for: req)
            while true {
                try await Task.sleep(nanoseconds: 250_000_000)
                guard let st = try await fetchJSON("api/build/\(id)") as? [String: Any] else { continue }
                let s = st["state"] as? String ?? ""
                progress(id, "building", st["step"] as? Int ?? 0, st["of"] as? Int ?? 6, 0,
                         st["label"] as? String ?? "")
                if s == "done" { break }
                if s == "error" {
                    // the cards in progress do not build: the last good build is still there to install
                    let why = st["error"] as? String ?? "build failed"
                    let good = (entry["build"] as? [String: Any])?["build"] as? String
                    if good == nil || good == state.library[id]?.build {
                        throw ArcadeError.message("The game's cards in progress don't build yet (\(why)). "
                                                  + (good == nil ? "There is no earlier build." : "You have the last good build."))
                    }
                    emit(["type": "notice", "id": id, "message": "The cards in progress don't build yet: installing the last good build instead."])
                    break
                }
                if cancelled { throw ArcadeError.message("cancelled") }
            }
            entry = try await fetchJSON("api/game/\(id)") as? [String: Any] ?? entry
        }
        guard let build = entry["build"] as? [String: Any], let mpath = build["manifest"] as? String else {
            throw ArcadeError.message("no build to download")
        }
        let (md, _) = try await URLSession.shared.data(from: base.appendingPathComponent(String(mpath.dropFirst())))
        let man = try JSONDecoder().decode(Manifest.self, from: md)
        let dest = installDir(id)
        let staging = libraryDir.appendingPathComponent("\(id).staging", isDirectory: true)
        try? FileManager.default.removeItem(at: staging)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
        // chunks we already have: from the installed build's files, if they are intact
        var have: [String: (URL, Int)] = [:]
        if let old = state.library[id], let od = try? Data(contentsOf: dest.appendingPathComponent(".manifest.json")),
           let om = try? JSONDecoder().decode(Manifest.self, from: od), old.build != man.build {
            for f in om.files {
                var off = 0
                for c in f.chunks { have[c.sha256] = (dest.appendingPathComponent(f.path), off); off += c.size }
            }
        }
        let need = man.files.flatMap { $0.chunks }.filter { have[$0.sha256] == nil }
        let total = need.reduce(0) { $0 + $1.size }
        var done = 0
        var window: [(Double, Int)] = []
        let t0 = Date().timeIntervalSince1970
        progress(id, "downloading", 0, total, 0)
        for f in man.files {
            var data = Data()
            for c in f.chunks {
                while paused { try await Task.sleep(nanoseconds: 200_000_000); if cancelled { break } }
                if cancelled { throw ArcadeError.message("cancelled") }
                var part: Data? = nil
                if let (url, off) = have[c.sha256], let h = try? FileHandle(forReadingFrom: url) {
                    try? h.seek(toOffset: UInt64(off))
                    let d = h.readData(ofLength: c.size)
                    try? h.close()
                    if sha256(d) == c.sha256 { part = d }
                }
                if part == nil {
                    var comps = URLComponents(url: base.appendingPathComponent("chunk/\(c.sha256)"), resolvingAgainstBaseURL: false)!
                    if state.settings.bandwidth > 0 { comps.queryItems = [URLQueryItem(name: "rate", value: "\(state.settings.bandwidth)")] }
                    let (d, r) = try await URLSession.shared.data(from: comps.url!)
                    guard (r as? HTTPURLResponse)?.statusCode == 200, sha256(d) == c.sha256 else {
                        throw ArcadeError.message("chunk \(c.sha256.prefix(12)) failed its check")
                    }
                    part = d
                    done += d.count
                    let now = Date().timeIntervalSince1970
                    window.append((now, done))
                    window = window.filter { now - $0.0 < 1.5 }
                    let rate = window.count > 1 ? Double(done - window[0].1) / max(0.05, now - window[0].0) : Double(done) / max(0.05, now - t0)
                    progress(id, "downloading", done, total, rate)
                }
                data.append(part!)
            }
            progress(id, "verifying", done, total, 0, f.path)
            guard sha256(data) == f.sha256 else { throw ArcadeError.message("\(f.path) failed its check") }
            let out = staging.appendingPathComponent(f.path)
            try FileManager.default.createDirectory(at: out.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: out)
            if f.executable { try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: out.path) }
        }
        progress(id, "installing", total, total, 0)
        try md.write(to: staging.appendingPathComponent(".manifest.json"))
        try? FileManager.default.removeItem(at: dest)
        try FileManager.default.moveItem(at: staging, to: dest)
        let prev = state.library[id]
        state.library[id] = Installed(version: man.version, build: man.build, size: man.size,
                                      installedAt: prev?.installedAt ?? Date().timeIntervalSince1970,
                                      playSeconds: prev?.playSeconds ?? 0, lastPlayed: prev?.lastPlayed ?? 0,
                                      app: man.app, executable: man.executable, manifest: mpath)
        save()
    }

    func verify(_ id: String) {
        Task {
            let dest = installDir(id)
            guard let d = try? Data(contentsOf: dest.appendingPathComponent(".manifest.json")),
                  let man = try? JSONDecoder().decode(Manifest.self, from: d) else {
                emit(["type": "verified", "id": id, "ok": false, "bad": -1]); return
            }
            var bad = 0
            for (k, f) in man.files.enumerated() {
                progress(id, "validating", k + 1, man.files.count, 0, f.path)
                let fd = (try? Data(contentsOf: dest.appendingPathComponent(f.path))) ?? Data()
                if sha256(fd) != f.sha256 { bad += 1 }
            }
            emit(["type": "verified", "id": id, "ok": bad == 0, "bad": bad, "files": man.files.count])
            if bad > 0 {
                state.library[id]?.build = "repair"
                startDownload(id)
            }
        }
    }

    func uninstall(_ id: String) {
        running[id]?.0.terminate()
        try? FileManager.default.removeItem(at: installDir(id))
        state.library[id] = nil
        save()
        emit(["type": "state", "state": snapshot()])
    }

    // -- playing -------------------------------------------------------------------------------------------------------
    func play(_ id: String) {
        guard let g = state.library[id], running[id] == nil else { return }
        let exe = installDir(id).appendingPathComponent(g.executable)
        let p = Process()
        p.executableURL = exe
        p.arguments = ["--save-dir", savesDir.appendingPathComponent(id).path]
        let started = Date().timeIntervalSince1970
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                let now = Date().timeIntervalSince1970
                self.running[id] = nil
                self.state.library[id]?.playSeconds += now - started
                self.state.library[id]?.lastPlayed = now
                self.save()
                self.emit(["type": "stopped", "id": id])
                self.emit(["type": "state", "state": self.snapshot()])
            }
        }
        do {
            try p.run()
            running[id] = (p, started)
            state.library[id]?.lastPlayed = started
            save()
            emit(["type": "running", "id": id])
            emit(["type": "state", "state": snapshot()])
        } catch {
            emit(["type": "error", "id": id, "message": "could not start: \(error)"])
        }
    }
}

extension Arcade {
    // a cartridge: the installed console player, started on the file where it is
    func playRom(_ id: String, player: String, path: String, title: String) {
        guard running[id] == nil else { return }
        guard let g = state.library[player] else {
            emit(["type": "error", "id": id, "message": "install the player first"]); return
        }
        guard FileManager.default.fileExists(atPath: path) else {
            emit(["type": "error", "id": id, "message": "the cartridge is not at \(path) any more"]); return
        }
        let p = Process()
        p.executableURL = installDir(player).appendingPathComponent(g.executable)
        p.arguments = ["--rom", path, "--title", title, "--save-dir", savesDir.appendingPathComponent(id).path]
        let started = Date().timeIntervalSince1970
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                let now = Date().timeIntervalSince1970
                self.running[id] = nil
                var c = self.state.played?[id] ?? Played(playSeconds: 0, lastPlayed: now)
                c.playSeconds += now - started
                c.lastPlayed = now
                if self.state.played == nil { self.state.played = [:] }
                self.state.played?[id] = c
                self.save()
                self.emit(["type": "stopped", "id": id])
                self.emit(["type": "state", "state": self.snapshot()])
            }
        }
        do {
            try p.run()
            running[id] = (p, started)
            if state.played == nil { state.played = [:] }
            var c = state.played?[id] ?? Played(playSeconds: 0, lastPlayed: started)
            c.lastPlayed = started
            state.played?[id] = c
            save()
            emit(["type": "running", "id": id])
            emit(["type": "state", "state": snapshot()])
        } catch {
            emit(["type": "error", "id": id, "message": "could not start: \(error)"])
        }
    }
}

let app = NSApplication.shared
let arcade = Arcade()
app.delegate = arcade
app.setActivationPolicy(.regular)
app.run()
