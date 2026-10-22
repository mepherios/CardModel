// Cardmodel Arcade on iPhone and iPad. The same pages as on the Mac (cards/app/arcade/ui), served by the Mac's arcade
// service and shown in a web view, and the native client those pages talk to (window.webkit.messageHandlers.arcade:
// the commands the Mac's Launcher.swift answers). It installs this device's build of a program (the service builds
// every game and console player for iOS from its cards; Client.swift checks every chunk and file), verifies and
// repairs it, and plays it inside this app with the iOS platform card's shell (GameShell.swift, compiled in). A
// cartridge stays on the Mac: the service sends its file when it is played, and it is kept in Caches.
//
// Which Mac: --service URL, else the one this device paired with, else 127.0.0.1:8770 (the Simulator and Mac
// Catalyst share the Mac's network). A device pairs once, with the Mac's address and the code `cardmodel arcade
// pair` shows there; the token is kept in the keychain and goes with every request (a cookie for the pages).
//
//   --service URL                the arcade service
//   --check ID                   install ID through the service, verify it, play it headless (--frames N --shot PATH
//                                --input SCRIPT; --rom ROMID: a cartridge of the Mac's library), print one JSON line
//                                and quit: the check `cardmodel arcade launcher --platform ios --check` runs
//   --open ID [--rom ROMID]      install ID if it is not, then play it (a cartridge with a player)
//   --mute                       games play without sound (scripted runs nobody is listening to)

import UIKit
import WebKit

#if targetEnvironment(macCatalyst)
let platformKey = "ios-maccatalyst"
#elseif targetEnvironment(simulator)
let platformKey = "ios-iphonesimulator"
#else
let platformKey = "ios-iphoneos"
#endif

// the service the build named (the Mac it was built on: 127.0.0.1 for the Simulator and Mac Catalyst, the Mac's
// address on the local network for a device), else this Mac's own
let defaultService = URL(string: Bundle.main.object(forInfoDictionaryKey: "CardmodelService") as? String ?? "")
    ?? URL(string: "http://127.0.0.1:8770")!
// on a phone or tablet the app's own container; as an iPad app on the Mac (not sandboxed) a folder of its own, never
// the Mac launcher's (its launcher.json and library are another program's)
#if targetEnvironment(macCatalyst)
let supportName = "Cardmodel Arcade (iPad app)"
#else
let supportName = "Cardmodel Arcade"
#endif
let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    .appendingPathComponent(supportName, isDirectory: true)
let libraryDir = support.appendingPathComponent("library", isDirectory: true)
let savesDir = support.appendingPathComponent("saves", isDirectory: true)
let controlsDir = support.appendingPathComponent("controls", isDirectory: true)
let stateFile = support.appendingPathComponent("launcher.json")
let cartridgeCache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    .appendingPathComponent(supportName, isDirectory: true).appendingPathComponent("cartridges", isDirectory: true)

struct Settings: Codable { var bandwidth: Int = 0 }
struct Played: Codable {
    var playSeconds: Double
    var lastPlayed: Double
    var title: String? = nil                  // a cartridge's title and player: it plays again without the Mac
    var player: String? = nil
}

struct LauncherState: Codable {
    var library: [String: Installed] = [:]
    var settings = Settings()
    var played: [String: Played]? = [:]       // cartridges, by id
    var service: String? = nil                // the paired Mac's service (nil: 127.0.0.1)
    var token: String? = nil                  // its token, where the keychain cannot keep it
}

struct LaunchOptions {
    var service: URL?
    var check: String?
    var open: String?
    var rom: String?
    var frames = 120
    var shot: String?
    var input = ""
    var mute = false
    init(arguments a: [String]) {
        var i = 1
        while i < a.count {
            let next = i + 1 < a.count ? a[i + 1] : ""
            switch a[i] {
            case "--service": service = URL(string: next); i += 1
            case "--check": check = next; i += 1
            case "--open": open = next; i += 1
            case "--rom": rom = next; i += 1
            case "--frames": frames = Int(next) ?? 120; i += 1
            case "--shot": shot = next; i += 1
            case "--input": input = next; i += 1
            case "--mute": mute = true
            default: break
            }
            i += 1
        }
    }
}

// the paired Mac's token: the keychain where the app may use it (a signed app), else the state file
enum Keychain {
    static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: "arcade-service"]
    static func load() -> String? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }
    static func save(_ token: String?) -> Bool {
        SecItemDelete(query as CFDictionary)
        guard let t = token else { return true }
        var add = query
        add[kSecValueData as String] = Data(t.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }
}

final class ArcadeController: UIViewController, WKScriptMessageHandler, WKNavigationDelegate {
    var web: WKWebView!
    var state = LauncherState()
    var service = Service(base: defaultService, token: nil)
    var client: Client?
    var download: Task<Void, Never>?
    var downloadId: String?
    var queue: [String] = []
    var running: (id: String, started: Double, cartridge: Bool)?
    let options = LaunchOptions(arguments: CommandLine.arguments)
    let splash = UILabel()
    let pairing = UIStackView()
    let hostField = UITextField()
    let codeField = UITextField()
    let pairStatus = UILabel()
    let offline = UIStackView()
    var opened = false

    override var preferredStatusBarStyle: UIStatusBarStyle { .lightContent }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.09, green: 0.10, blue: 0.13, alpha: 1)
        for d in [libraryDir, savesDir, controlsDir, cartridgeCache] {
            try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        }
        load()
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "arcade")
        cfg.applicationNameForUserAgent = "CardmodelArcade CardmodelPlatform/\(platformKey)"
        // the pages are the Mac's; on a touch screen they also get touch.css (beside them in the ui folder)
        let touch = "document.documentElement.classList.add('ios');var l=document.createElement('link');"
            + "l.rel='stylesheet';l.href='/ui/touch.css';document.head.appendChild(l);"
        cfg.userContentController.addUserScript(WKUserScript(source: touch, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.isOpaque = false
        web.backgroundColor = view.backgroundColor
        web.scrollView.backgroundColor = view.backgroundColor
        if #available(iOS 16.4, *) { web.isInspectable = true }
        web.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(web)
        let g = view.safeAreaLayoutGuide
        NSLayoutConstraint.activate([web.topAnchor.constraint(equalTo: g.topAnchor), web.bottomAnchor.constraint(equalTo: g.bottomAnchor),
                                     web.leadingAnchor.constraint(equalTo: g.leadingAnchor), web.trailingAnchor.constraint(equalTo: g.trailingAnchor)])
        splash.textColor = UIColor(red: 0.78, green: 0.84, blue: 0.88, alpha: 1)
        splash.textAlignment = .center
        splash.numberOfLines = 0
        splash.font = .systemFont(ofSize: 15)
        splash.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(splash)
        NSLayoutConstraint.activate([splash.centerXAnchor.constraint(equalTo: g.centerXAnchor), splash.centerYAnchor.constraint(equalTo: g.centerYAnchor),
                                     splash.widthAnchor.constraint(lessThanOrEqualTo: g.widthAnchor, constant: -48)])
        buildPairing()
        offline.axis = .vertical
        offline.spacing = 12
        offline.isHidden = true
        offline.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(offline)
        NSLayoutConstraint.activate([offline.centerXAnchor.constraint(equalTo: g.centerXAnchor),
                                     offline.centerYAnchor.constraint(equalTo: g.centerYAnchor),
                                     offline.widthAnchor.constraint(equalToConstant: 340)])
        show("CARDMODEL ARCADE\n\nLooking for the arcade service on your Mac…")
        Task { await self.connect() }
    }

    func show(_ text: String?) {
        splash.text = text
        splash.isHidden = text == nil
        web.isHidden = text != nil
    }

    // -- the Mac ----------------------------------------------------------------------------------------------------
    func token() -> String? { Keychain.load() ?? state.token }

    func connect() async {
        pairing.isHidden = true
        offline.isHidden = true
        if let s = options.service {
            service = Service(base: s, token: token())
        } else if let saved = state.service, let url = URL(string: saved) {
            service = Service(base: url, token: token())
        } else {
            service = Service(base: defaultService, token: nil)
        }
        var up = false
        for _ in 0..<6 {
            if await service.alive() { up = true; break }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        if up, (try? await service.data("api/pair").1) == 401 { up = false }     // a token the Mac forgot
        guard up else {
            if options.check != nil { finishCheck(["ok": false, "error": "no arcade service at \(service.base.absoluteString)"]) }
            if state.library.isEmpty { showPairing() } else { showOffline() }
            return
        }
        let c = Client(service: service, platform: platformKey, library: libraryDir)
        c.bandwidth = state.settings.bandwidth
        client = c
        if let o = options.check { await runCheck(o); return }
        if let t = service.token, let host = service.base.host,
           let cookie = HTTPCookie(properties: [.domain: host, .path: "/", .name: "cardmodel_device", .value: t,
                                                .expires: Date(timeIntervalSinceNow: 3600 * 24 * 365)]) {
            await web.configuration.websiteDataStore.httpCookieStore.setCookie(cookie)
        }
        web.load(URLRequest(url: service.url("ui/index.html")))
    }

    func webView(_ w: WKWebView, didFinish nav: WKNavigation!) {
        show(nil)
        if let id = options.open, !opened {
            opened = true
            openOnStart(id)
        }
    }
    func webView(_ w: WKWebView, didFailProvisionalNavigation nav: WKNavigation!, withError error: Error) { retry() }
    func webView(_ w: WKWebView, didFail nav: WKNavigation!, withError error: Error) { retry() }
    func webViewWebContentProcessDidTerminate(_ w: WKWebView) { retry() }
    func retry() {
        show("Reconnecting to the arcade service…")
        Task {
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            await self.connect()
        }
    }

    // pairing: the Mac's address and the code `cardmodel arcade pair` shows there
    func buildPairing() {
        let title = UILabel()
        title.text = "Pair with your Mac"
        title.font = .boldSystemFont(ofSize: 22)
        title.textColor = .white
        let text = UILabel()
        text.numberOfLines = 0
        text.font = .systemFont(ofSize: 15)
        text.textColor = UIColor(red: 0.78, green: 0.84, blue: 0.88, alpha: 1)
        text.text = "The store, the builds and your cartridges live on your Mac. On the Mac, run\n\n    cardmodel arcade pair\n\n"
            + "and type the address and the code it shows."
        for (f, p) in [(hostField, "Mac address (for example your-mac.local:8770)"), (codeField, "Code")] {
            f.placeholder = p
            f.borderStyle = .roundedRect
            f.autocapitalizationType = .none
            f.autocorrectionType = .no
            f.backgroundColor = UIColor(white: 1, alpha: 0.92)
        }
        hostField.keyboardType = .URL
        let known = state.service.flatMap { URL(string: $0) } ?? defaultService
        hostField.text = "\(known.host ?? ""):\(known.port ?? 8770)"
        codeField.keyboardType = .numberPad
        let button = UIButton(type: .system)
        button.setTitle("Pair", for: .normal)
        button.titleLabel?.font = .boldSystemFont(ofSize: 17)
        button.addTarget(self, action: #selector(pair), for: .touchUpInside)
        let again = UIButton(type: .system)
        again.setTitle("Look again", for: .normal)
        again.addTarget(self, action: #selector(lookAgain), for: .touchUpInside)
        pairStatus.numberOfLines = 0
        pairStatus.font = .systemFont(ofSize: 14)
        pairStatus.textColor = UIColor(red: 0.9, green: 0.6, blue: 0.5, alpha: 1)
        for v in [title, text, hostField, codeField, button, again, pairStatus] { pairing.addArrangedSubview(v) }
        pairing.axis = .vertical
        pairing.spacing = 14
        pairing.isHidden = true
        pairing.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(pairing)
        let g = view.safeAreaLayoutGuide
        // in the middle, unless the keyboard needs the room: then just above it
        let middle = pairing.centerYAnchor.constraint(equalTo: g.centerYAnchor)
        middle.priority = .defaultHigh
        NSLayoutConstraint.activate([pairing.centerXAnchor.constraint(equalTo: g.centerXAnchor), middle,
                                     pairing.bottomAnchor.constraint(lessThanOrEqualTo: view.keyboardLayoutGuide.topAnchor, constant: -16),
                                     pairing.topAnchor.constraint(greaterThanOrEqualTo: g.topAnchor, constant: 8),
                                     pairing.widthAnchor.constraint(equalToConstant: 340)])
    }

    func showPairing() {
        show(nil)
        web.isHidden = true
        hostField.text = "\(service.base.host ?? ""):\(service.base.port ?? 8770)"     // the Mac it just tried
        pairing.isHidden = false
    }

    @objc func lookAgain() { Task { await self.connect() } }
    @objc func pairInstead() { offline.isHidden = true; showPairing() }

    // the Mac is not there: what is installed here plays without it (programs, and cartridges played before)
    func showOffline() {
        show(nil)
        web.isHidden = true
        pairing.isHidden = true
        offline.arrangedSubviews.forEach { $0.removeFromSuperview() }
        let title = UILabel()
        title.text = "Your Mac is not reachable"
        title.font = .boldSystemFont(ofSize: 22)
        title.textColor = .white
        let text = UILabel()
        text.numberOfLines = 0
        text.font = .systemFont(ofSize: 15)
        text.textColor = UIColor(red: 0.78, green: 0.84, blue: 0.88, alpha: 1)
        text.text = "The store and updates come from the Mac. What is installed on this device plays without it:"
        offline.addArrangedSubview(title)
        offline.addArrangedSubview(text)
        func button(_ label: String, _ action: @escaping () -> Void) {
            let b = UIButton(type: .system, primaryAction: UIAction { _ in action() })
            b.setTitle(label, for: .normal)
            b.contentHorizontalAlignment = .leading
            b.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
            offline.addArrangedSubview(b)
        }
        for (id, g) in state.library.sorted(by: { $0.key < $1.key }) {
            let man = (try? Data(contentsOf: installDir(id).appendingPathComponent(".manifest.json")))
                .flatMap { try? JSONDecoder().decode(Manifest.self, from: $0) }
            button("\u{25B6}  " + (man?.title ?? g.app)) { [weak self] in self?.play(id) }
        }
        for (romId, p) in (state.played ?? [:]).sorted(by: { $0.value.lastPlayed > $1.value.lastPlayed }) {
            guard let player = p.player, state.library[player] != nil,
                  let file = (try? FileManager.default.contentsOfDirectory(at: cartridgeCache.appendingPathComponent(romId),
                                                                            includingPropertiesForKeys: nil))?
                    .first(where: { !$0.lastPathComponent.hasPrefix(".") }) else { continue }
            button("\u{25B6}  " + (p.title ?? file.deletingPathExtension().lastPathComponent)) { [weak self] in
                self?.play(player, rom: file, saveId: romId, title: p.title)
            }
        }
        let again = UIButton(type: .system)
        again.setTitle("Look for the Mac again", for: .normal)
        again.addTarget(self, action: #selector(lookAgain), for: .touchUpInside)
        let pairButton = UIButton(type: .system)
        pairButton.setTitle("Pair with a Mac", for: .normal)
        pairButton.addTarget(self, action: #selector(pairInstead), for: .touchUpInside)
        offline.addArrangedSubview(again)
        offline.addArrangedSubview(pairButton)
        offline.isHidden = false
    }

    @objc func pair() {
        var host = (hostField.text ?? "").trimmingCharacters(in: .whitespaces)
        if !host.contains("://") { host = "http://" + host }
        guard var url = URL(string: host), url.host != nil else { pairStatus.text = "That is not an address."; return }
        if url.port == nil, let u = URL(string: "\(url.scheme ?? "http")://\(url.host!):8770") { url = u }
        let code = String((codeField.text ?? "").filter(\.isNumber).prefix(6))     // "123 456" as the Mac prints it
        pairStatus.text = "Pairing…"
        Task {
            let body = try? JSONSerialization.data(withJSONObject: ["code": code, "name": UIDevice.current.name])
            do {
                let o = try await Service(base: url, token: nil).json("api/pair", method: "POST", body: body)
                guard let t = o["token"] as? String else { throw ArcadeError.message("no token") }
                state.service = url.absoluteString
                state.token = Keychain.save(t) ? nil : t
                save()
                pairStatus.text = ""
                view.endEditing(true)
                await connect()
            } catch {
                pairStatus.text = "The Mac did not take that code (it is good for ten minutes and five tries): \(error)"
            }
        }
    }

    // -- state -------------------------------------------------------------------------------------------------------
    func load() {
        if let d = try? Data(contentsOf: stateFile), let s = try? JSONDecoder().decode(LauncherState.self, from: d) { state = s }
    }
    func save() {
        if let d = try? JSONEncoder().encode(state) { try? d.write(to: stateFile, options: .atomic) }
    }
    func installDir(_ id: String) -> URL { libraryDir.appendingPathComponent(id, isDirectory: true) }
    func controlsFile(_ id: String) -> URL { controlsDir.appendingPathComponent(id + ".json") }

    func achievements(_ id: String) -> [Int] {
        let f = savesDir.appendingPathComponent(id).appendingPathComponent("save.bin")
        guard let d = try? Data(contentsOf: f), d.count > 48 else { return [] }
        return (32..<48).map { Int(d[$0]) }
    }

    func snapshot() -> [String: Any] {
        let now = Date().timeIntervalSince1970
        func live(_ id: String) -> Double { running?.id == id ? now - running!.started : 0 }
        var lib: [String: Any] = [:]
        for (id, g) in state.library {
            lib[id] = ["version": g.version, "build": g.build, "size": g.size, "installedAt": g.installedAt,
                       "playSeconds": g.playSeconds + live(id), "lastPlayed": g.lastPlayed,
                       "running": running?.id == id, "achievements": achievements(id), "source": ""]
        }
        var carts: [String: Any] = [:]
        for (id, c) in state.played ?? [:] {
            carts[id] = ["playSeconds": c.playSeconds + live(id), "lastPlayed": c.lastPlayed, "running": running?.id == id]
        }
        if let r = running, r.cartridge, carts[r.id] == nil {
            carts[r.id] = ["playSeconds": now - r.started, "lastPlayed": now, "running": true]
        }
        var controls: [String: Any] = [:]
        for f in (try? FileManager.default.contentsOfDirectory(at: controlsDir, includingPropertiesForKeys: nil)) ?? []
            where f.pathExtension == "json" {
            if let d = try? Data(contentsOf: f), let o = try? JSONSerialization.jsonObject(with: d) {
                controls[f.deletingPathExtension().lastPathComponent] = o
            }
        }
        return ["library": lib, "played": carts, "controls": controls,
                "settings": ["bandwidth": state.settings.bandwidth, "user": UIDevice.current.name],
                "downloading": downloadId as Any, "paused": client?.paused ?? false, "native": true,
                "libraryPath": libraryDir.path, "platform": platformKey,
                "device": UIDevice.current.userInterfaceIdiom == .pad ? "iPad" : "iPhone",
                "service": service.base.absoluteString]
    }

    // -- the pages talk to us ----------------------------------------------------------------------------------------
    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let cmd = body["cmd"] as? String else { return }
        let id = body["id"] as? String ?? ""
        switch cmd {
        case "state": emitState()
        case "reconnect": Task { await self.connect() }
        case "install", "update": startDownload(id)
        case "pause": client?.paused = true; emitState()
        case "resume": client?.paused = false; emitState()
        case "cancel": client?.cancelled = true; client?.paused = false; queue.removeAll()
        case "play": play(id)
        case "play_rom": playRom(id, player: body["player"] as? String ?? "", title: body["title"] as? String ?? "")
        case "stop": (presentedViewController as? GameViewController)?.close()
        case "verify": verify(id)
        case "uninstall": uninstall(id)
        case "settings":
            if let b = body["bandwidth"] as? Int { state.settings.bandwidth = b; client?.bandwidth = b }
            save()
            emitState()
        case "controls":
            // {id, controls: {keys, keys2, gamepad}} keeps them; {id} without controls goes back to the game's own
            if let ctl = body["controls"] as? [String: Any], !id.isEmpty,
               let d = try? JSONSerialization.data(withJSONObject: ctl, options: [.sortedKeys]) {
                try? d.write(to: controlsFile(id), options: .atomic)
            } else if !id.isEmpty {
                try? FileManager.default.removeItem(at: controlsFile(id))
            }
            emitState()
        case "pick_folder", "reveal_rom", "reveal_path", "reveal":
            say("On your Mac", cmd == "pick_folder" ? "Cartridge folders are chosen in Cardmodel Arcade on the Mac; "
                + "this device plays every cartridge the Mac's library lists." : "That is on your Mac.")
        default: break
        }
    }

    func say(_ title: String, _ text: String) {
        let a = UIAlertController(title: title, message: text, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default))
        present(a, animated: true)
    }

    func emit(_ obj: [String: Any]) {
        guard let d = try? JSONSerialization.data(withJSONObject: obj), let s = String(data: d, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.arcade && window.arcade.event(\(s))")
    }
    func emitState() { emit(["type": "state", "state": snapshot()]) }

    func progress(_ id: String, _ phase: String, _ done: Int, _ total: Int, _ rate: Double, _ label: String) {
        emit(["type": "progress", "id": id, "phase": phase, "done": done, "total": total, "rate": rate, "label": label])
    }

    // -- installing --------------------------------------------------------------------------------------------------
    // one at a time; what is asked for meanwhile waits its turn
    func startDownload(_ id: String) {
        guard let c = client, !id.isEmpty else { return }
        if download != nil {
            if id != downloadId && !queue.contains(id) { queue.append(id) }
            return
        }
        downloadId = id
        c.paused = false
        c.cancelled = false
        emitState()
        download = Task {
            do {
                let inst = try await c.install(id, previous: state.library[id], progress: { ph, d, t, r, l in
                    Task { @MainActor in self.progress(id, ph, d, t, r, l) }
                }, notice: { m in
                    Task { @MainActor in self.emit(["type": "notice", "id": id, "message": m]) }
                })
                state.library[id] = inst
                save()
                emit(["type": "done", "id": id])
            } catch {
                emit(["type": "error", "id": id, "message": "\(error)"])
            }
            download = nil
            downloadId = nil
            emitState()
            if !queue.isEmpty { startDownload(queue.removeFirst()) }
        }
    }

    func verify(_ id: String) {
        guard let c = client else { return }
        Task {
            let (bad, files) = await Task.detached { c.verify(id) { ph, d, t, r, l in Task { @MainActor in self.progress(id, ph, d, t, r, l) } } }.value
            emit(["type": "verified", "id": id, "ok": bad == 0, "bad": bad, "files": files])
            if bad != 0 {
                state.library[id]?.build = "repair"
                startDownload(id)
            }
        }
    }

    func uninstall(_ id: String) {
        if running?.id == id { (presentedViewController as? GameViewController)?.close() }
        try? FileManager.default.removeItem(at: installDir(id))
        state.library[id] = nil
        save()
        emitState()
    }

    // -- playing -----------------------------------------------------------------------------------------------------
    // a program, or a cartridge (rom) in its player: the shell inside this app, its save in the program's (or the
    // cartridge's) own folder, the player's own controls when the Controls page kept some
    func play(_ id: String, rom: URL? = nil, saveId: String? = nil, title: String? = nil) {
        guard running == nil, let g = state.library[id] else { return }
        let sid = saveId ?? id
        var o = GameOptions()
        o.saveDir = savesDir.appendingPathComponent(sid, isDirectory: true)
        o.rom = rom?.path
        o.title = title
        o.mute = options.mute
        o.controls = [sid, id].map { controlsFile($0) }.first { FileManager.default.fileExists(atPath: $0.path) }?.path
        let vc = GameViewController(bundle: installDir(id).appendingPathComponent(g.app), options: o)
        let started = Date().timeIntervalSince1970
        vc.onExit = { [weak self, weak vc] err in
            guard let self = self else { return }
            vc?.dismiss(animated: true)
            let now = Date().timeIntervalSince1970
            if rom != nil {
                var c = self.state.played?[sid] ?? Played(playSeconds: 0, lastPlayed: now)
                c.playSeconds += now - started
                c.lastPlayed = now
                c.title = title.flatMap { $0.isEmpty ? nil : $0 } ?? c.title
                c.player = id
                if self.state.played == nil { self.state.played = [:] }
                self.state.played?[sid] = c
            } else {
                self.state.library[id]?.playSeconds += now - started
                self.state.library[id]?.lastPlayed = now
            }
            self.running = nil
            self.save()
            if let e = err { self.emit(["type": "error", "id": sid, "message": "could not start: \(e)"]) }
            self.emit(["type": "stopped", "id": sid])
            self.emitState()
        }
        running = (sid, started, rom != nil)
        present(vc, animated: true)
        emit(["type": "running", "id": sid])
        emitState()
    }

    func playRom(_ romId: String, player: String, title: String) {
        guard running == nil, let c = client else { return }
        guard state.library[player] != nil else {
            emit(["type": "error", "id": romId, "message": "install the player first"]); return
        }
        progress(romId, "preparing", 0, 1, 0, "the cartridge from your Mac")
        Task {
            do {
                let file = try await c.cartridge(romId, cache: cartridgeCache)
                emit(["type": "done", "id": romId])
                play(player, rom: file, saveId: romId, title: title)
            } catch {
                emit(["type": "error", "id": romId, "message": "\(error)"])
            }
        }
    }

    // --open: install if needed, then play (a cartridge with --rom: its player)
    func openOnStart(_ id: String) {
        Task {
            if state.library[id] == nil, let c = client {
                do {
                    state.library[id] = try await c.install(id, previous: nil, progress: { _, _, _, _, _ in }, notice: { _ in })
                    save()
                } catch { say("Could not install \(id)", "\(error)"); return }
            }
            emitState()
            if let r = options.rom { playRom(r, player: id, title: "") } else { play(id) }
        }
    }

    // --check: what the store does on this device, headless, as one JSON line
    func runCheck(_ id: String) async {
        guard let c = client else { return }
        var out: [String: Any] = ["program": id, "platform": platformKey, "service": service.base.absoluteString]
        do {
            let t0 = Date()
            let inst = try await c.install(id, previous: state.library[id], progress: { _, _, _, _, _ in }, notice: { _ in })
            state.library[id] = inst
            save()
            out["install"] = ["version": inst.version, "build": inst.build, "size": inst.size,
                              "seconds": (Date().timeIntervalSince(t0) * 10).rounded() / 10]
            let v = c.verify(id) { _, _, _, _, _ in }
            out["verify"] = ["bad": v.bad, "files": v.files]
            var o = GameOptions()
            o.frames = options.frames
            o.shot = options.shot
            o.input = options.input
            o.saveDir = FileManager.default.temporaryDirectory.appendingPathComponent("check-\(UUID().uuidString)")
            if let r = options.rom {
                let file = try await c.cartridge(r, cache: cartridgeCache)
                o.rom = file.path
                out["cartridge"] = file.lastPathComponent
            }
            let g = try Game(bundle: installDir(id).appendingPathComponent(inst.app), saveDir: o.saveDir, romPath: o.rom)
            out["play"] = g.headless(o)
            g.close()
            out["ok"] = v.bad == 0
        } catch {
            out["ok"] = false
            out["error"] = "\(error)"
        }
        finishCheck(out)
    }

    func finishCheck(_ out: [String: Any]) {
        if let d = try? JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]), let s = String(data: d, encoding: .utf8) {
            print("arcade check: " + s)
        }
        fflush(stdout)
        exit((out["ok"] as? Bool) == true ? 0 : 1)
    }
}

@main
final class LauncherApp: UIResponder, UIApplicationDelegate {
    func application(_ app: UIApplication, configurationForConnecting session: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let c = UISceneConfiguration(name: "Arcade", sessionRole: session.role)
        c.delegateClass = LauncherScene.self
        return c
    }
}

final class LauncherScene: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let ws = scene as? UIWindowScene else { return }
        #if targetEnvironment(macCatalyst)
        ws.sizeRestrictions?.minimumSize = CGSize(width: 1040, height: 680)
        ws.title = "Cardmodel Arcade"
        #endif
        let w = UIWindow(windowScene: ws)
        w.rootViewController = ArcadeController()
        window = w
        w.makeKeyAndVisible()
    }
}
