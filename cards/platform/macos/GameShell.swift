// The native effect shell for a card-model game on macOS (CM21): a window, the keyboard and gamepads, sound and
// the save file. It knows nothing about the game. Contents/Resources/game.json (written by `cardmodel arcade
// build` from the game card) says which symbols of Contents/Frameworks/game.dylib are the frame function, the
// screen, the sound, the input bits and the save; the game decides everything else.
//
//   --frames N          run N frames and quit (tests)
//   --shot PATH         with --frames: write the last frame as a PNG
//   --input SCRIPT      frame:button+button,... pressed for one frame each (tests)
//   --save-dir DIR      where save.bin lives (default ~/Library/Application Support/Cardmodel Arcade/saves/ID)
//   --rom PATH          a cartridge, for a console player (game.json has "cartridge"; its "path" when no --rom,
//                       an app made for one cartridge): read where it is (a .zip
//                       in memory), its bytes copied into the module, which decodes it
//   --title TEXT        the window's title

import AppKit
import AVFoundation
import Compression
import GameController
import ImageIO
import UniformTypeIdentifiers

struct Spec: Decodable {
    struct Screen: Decodable { let width: Int; let height: Int; let scale: Int; let symbol: String }
    struct Audio: Decodable { let rate: Double; let symbol: String; let count: String }
    struct Save: Decodable { let symbol: String; let dirty: String; let bytes: Int }
    struct Entry: Decodable { let reset: String; let initFn: String; let frame: String; let quit: String; let fullscreen: String }
    let id: String
    let title: String
    let screen: Screen
    let audio: Audio
    let save: Save
    let entry: Entry
    let bits: [String]
    let keys: [String: [String]]
    let keys2: [String: [String]]
    let gamepad: [String: String]
    struct Cartridge: Decodable { let symbol: String; let bytes: Int; let load: String; let extensions: [String]; let zip: Bool
                                  let path: String? }
    struct Keep: Decodable { let symbol: String; let bytes: Int; let file: String; let mode: String? }
    let cartridge: Cartridge?      // a console player: the cartridge array and the function that decodes it
    let keep: [Keep]?              // arrays kept beside the save: bits ORed in ("or"), or bytes that are set copied
                                   // over ("copy"): what ran where, for the next build of an app for one cartridge
    let globals: [String: Int64]?  // Int64 globals set before the module starts (e.g. profiling on)
    let clock: String?             // an Int64 the shell keeps at the Unix time (a cartridge's real-time clock)
    let flush: String?             // called before the shell quits (unsaved battery RAM)
}

typealias VoidFn = @convention(c) () -> Void
typealias FrameFn = @convention(c) (Int64, Int64) -> Int64
typealias LoadFn = @convention(c) (Int64) -> Void

// a cartridge file's bytes: the file itself, or the first member of a .zip with one of the extensions
func readCartridge(_ path: String, _ exts: [String]) -> Data? {
    guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { return nil }
    if !path.lowercased().hasSuffix(".zip") { return data }
    let b = [UInt8](data)
    func u16(_ o: Int) -> Int { Int(b[o]) | Int(b[o + 1]) << 8 }
    func u32(_ o: Int) -> Int { u16(o) | u16(o + 2) << 16 }
    guard b.count >= 22 else { return nil }
    var eocd = b.count - 22
    while eocd >= 0 && u32(eocd) != 0x06054b50 { eocd -= 1 }
    guard eocd >= 0 else { return nil }
    var o = u32(eocd + 16)
    for _ in 0..<u16(eocd + 10) {
        guard o + 46 <= b.count, u32(o) == 0x02014b50 else { return nil }
        let method = u16(o + 10), csize = u32(o + 20), usize = u32(o + 24)
        let nlen = u16(o + 28), elen = u16(o + 30), clen = u16(o + 32), local = u32(o + 42)
        let name = String(decoding: b[(o + 46)..<(o + 46 + nlen)], as: UTF8.self).lowercased()
        o += 46 + nlen + elen + clen
        guard exts.contains(where: { name.hasSuffix($0) }), local + 30 <= b.count else { continue }
        let start = local + 30 + u16(local + 26) + u16(local + 28)
        guard start + csize <= b.count else { return nil }
        if method == 0 { return Data(b[start..<(start + csize)]) }
        guard method == 8 else { return nil }
        var out = [UInt8](repeating: 0, count: max(usize, 1))
        let n = b.withUnsafeBufferPointer { src in
            compression_decode_buffer(&out, usize, src.baseAddress! + start, csize, nil, COMPRESSION_ZLIB)
        }
        return n == usize ? Data(out[0..<n]) : nil
    }
    return nil
}

final class Game {
    let spec: Spec
    let frameFn: FrameFn
    let fb: UnsafeMutablePointer<UInt8>
    let audio: UnsafeMutablePointer<UInt8>
    let audioN: UnsafeMutablePointer<Int64>
    let save: UnsafeMutablePointer<UInt8>
    let saveDirty: UnsafeMutablePointer<Int64>
    let quit: UnsafeMutablePointer<Int64>
    let fullscreen: UnsafeMutablePointer<Int64>
    let saveURL: URL
    var clock: UnsafeMutablePointer<Int64>?
    var flushFn: VoidFn?
    var kept: [(UnsafeMutablePointer<UInt8>, Spec.Keep)] = []

    init(bundle: Bundle, saveDir: URL?, romPath: String?) {
        let specURL = bundle.url(forResource: "game", withExtension: "json")!
        spec = try! JSONDecoder().decode(Spec.self, from: Data(contentsOf: specURL))
        let libPath = bundle.privateFrameworksPath! + "/game.dylib"
        guard let h = dlopen(libPath, RTLD_NOW) else { fatalError("cannot load \(libPath): \(String(cString: dlerror()))") }
        func sym(_ n: String) -> UnsafeMutableRawPointer {
            guard let p = dlsym(h, n) else { fatalError("game.dylib has no \(n)") }
            return p
        }
        frameFn = unsafeBitCast(sym(spec.entry.frame), to: FrameFn.self)
        fb = sym(spec.screen.symbol).assumingMemoryBound(to: UInt8.self)
        audio = sym(spec.audio.symbol).assumingMemoryBound(to: UInt8.self)
        audioN = sym(spec.audio.count).assumingMemoryBound(to: Int64.self)
        save = sym(spec.save.symbol).assumingMemoryBound(to: UInt8.self)
        saveDirty = sym(spec.save.dirty).assumingMemoryBound(to: Int64.self)
        quit = sym(spec.entry.quit).assumingMemoryBound(to: Int64.self)
        fullscreen = sym(spec.entry.fullscreen).assumingMemoryBound(to: Int64.self)
        let dir = saveDir ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cardmodel Arcade/saves/\(spec.id)", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        saveURL = dir.appendingPathComponent("save.bin")
        unsafeBitCast(sym(spec.entry.reset), to: VoidFn.self)()
        if let c = spec.cartridge {
            guard let path = romPath ?? c.path else { fatalError("\(spec.title) plays a cartridge: start it with --rom PATH") }
            guard let data = readCartridge(path, c.extensions) else { fatalError("cannot read a cartridge from \(path)") }
            let dst = sym(c.symbol).assumingMemoryBound(to: UInt8.self)
            let n = min(data.count, c.bytes)
            data.withUnsafeBytes { raw in _ = memcpy(dst, raw.baseAddress!, n) }
            unsafeBitCast(sym(c.load), to: LoadFn.self)(Int64(n))
        }
        if let c = spec.clock {
            clock = sym(c).assumingMemoryBound(to: Int64.self)
            clock?.pointee = Int64(Date().timeIntervalSince1970)
        }
        if let f = spec.flush { flushFn = unsafeBitCast(sym(f), to: VoidFn.self) }
        for (name, value) in spec.globals ?? [:] { sym(name).assumingMemoryBound(to: Int64.self).pointee = value }
        for k in spec.keep ?? [] { kept.append((sym(k.symbol).assumingMemoryBound(to: UInt8.self), k)) }
        if let data = try? Data(contentsOf: saveURL) {
            data.withUnsafeBytes { raw in
                let n = min(raw.count, spec.save.bytes)
                for i in 0..<n { save[i] = raw[i] }
            }
        }
        unsafeBitCast(sym(spec.entry.initFn), to: VoidFn.self)()
    }

    func step(_ p1: Int64, _ p2: Int64) -> Bool {
        clock?.pointee = Int64(Date().timeIntervalSince1970)
        let q = frameFn(p1, p2)
        if saveDirty.pointee != 0 { writeSave() }
        return q != 0
    }

    // before quitting: let the module save what it has not, then write it; merge the kept bit arrays
    func finish() {
        flushFn?()
        if saveDirty.pointee != 0 { writeSave() }
        for (ptr, k) in kept {
            let url = saveURL.deletingLastPathComponent().appendingPathComponent(k.file)
            var bytes = [UInt8]((try? Data(contentsOf: url)) ?? Data())
            if bytes.count < k.bytes { bytes += [UInt8](repeating: 0, count: k.bytes - bytes.count) }
            if k.mode == "copy" {
                for i in 0..<k.bytes where ptr[i] != 0 { bytes[i] = ptr[i] }
            } else {
                for i in 0..<k.bytes { bytes[i] |= ptr[i] }
            }
            try? Data(bytes).write(to: url, options: .atomic)
        }
    }

    func writeSave() {
        saveDirty.pointee = 0
        let data = Data(bytes: save, count: spec.save.bytes)
        try? data.write(to: saveURL, options: .atomic)
    }

    func image() -> CGImage {
        let w = spec.screen.width, h = spec.screen.height
        let data = Data(bytes: fb, count: w * h * 4)
        let provider = CGDataProvider(data: data as CFData)!
        return CGImage(width: w, height: h, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: w * 4,
                       space: CGColorSpace(name: CGColorSpace.sRGB)!,
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
    }

    // the frame's sound, as float stereo samples
    func drainAudio(into ring: Ring) {
        let n = Int(audioN.pointee)
        audioN.pointee = 0
        var i = 0
        while i + 3 < n {
            let l = Int16(bitPattern: UInt16(audio[i]) | (UInt16(audio[i + 1]) << 8))
            let r = Int16(bitPattern: UInt16(audio[i + 2]) | (UInt16(audio[i + 3]) << 8))
            ring.push(Float(l) / 32768, Float(r) / 32768)
            i += 4
        }
    }
}

// a ring of stereo samples between the frame loop and the audio thread
final class Ring {
    private var buf: [Float]
    private var r = 0, w = 0
    private let lock = NSLock()
    init(frames: Int) { buf = [Float](repeating: 0, count: frames * 2) }
    var count: Int { lock.lock(); defer { lock.unlock() }; return (w - r + buf.count) % buf.count / 2 }
    func push(_ l: Float, _ rr: Float) {
        lock.lock()
        buf[w] = l; buf[w + 1] = rr
        w = (w + 2) % buf.count
        if w == r { r = (r + 2) % buf.count }
        lock.unlock()
    }
    func pop(_ n: Int, _ left: UnsafeMutablePointer<Float>, _ right: UnsafeMutablePointer<Float>) {
        lock.lock()
        for k in 0..<n {
            if r == w { left[k] = 0; right[k] = 0; continue }
            left[k] = buf[r]; right[k] = buf[r + 1]
            r = (r + 2) % buf.count
        }
        lock.unlock()
    }
}

// key names (game card) to macOS virtual key codes
let keyCodes: [String: UInt16] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45,
    "m": 46, "return": 36, "tab": 48, "space": 49, "backspace": 51, "escape": 53, "left": 123, "right": 124,
    "down": 125, "up": 126, "keypad0": 82, "keypad1": 83, "keypad2": 84, "keypad3": 85, "keypad4": 86,
    "keypad5": 87, "keypad6": 88, "keypad7": 89, "keypad8": 91, "keypad9": 92, "keypadenter": 76,
]

final class Screen: NSView {
    override var acceptsFirstResponder: Bool { true }
    override func keyDown(with event: NSEvent) {}
    override func keyUp(with event: NSEvent) {}
    override func layout() {
        super.layout()
        layer?.frame = bounds
    }
}

final class Shell: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var game: Game!
    var window: NSWindow!
    let view = Screen()
    let ring = Ring(frames: 48000)
    let engine = AVAudioEngine()
    var held = Set<UInt16>()
    var map1: [UInt16: Int64] = [:]
    var map2: [UInt16: Int64] = [:]
    var timer: Timer?
    var last = CACurrentMediaTime()
    var acc = 0.0
    var maxFrames = -1
    var frames = 0
    var shotPath: String?
    var script: [Int: Int64] = [:]
    var saveDir: URL?
    var scriptText = ""
    var romPath: String?
    var titleText: String?

    func applicationDidFinishLaunching(_ note: Notification) {
        parseArgs()
        game = Game(bundle: Bundle.main, saveDir: saveDir, romPath: romPath)
        parseScript(scriptText)
        let s = game.spec
        for (name, keys) in s.keys { if let b = s.bits.firstIndex(of: name) { for k in keys { if let c = keyCodes[k] { map1[c, default: 0] |= 1 << Int64(b) } } } }
        for (name, keys) in s.keys2 { if let b = s.bits.firstIndex(of: name) { for k in keys { if let c = keyCodes[k] { map2[c, default: 0] |= 1 << Int64(b) } } } }
        if maxFrames >= 0 { headless(); return }
        let w = CGFloat(s.screen.width * s.screen.scale), h = CGFloat(s.screen.height * s.screen.scale)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: w, height: h),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = titleText ?? s.title
        window.contentAspectRatio = NSSize(width: s.screen.width, height: s.screen.height)
        window.collectionBehavior = [.fullScreenPrimary]
        window.backgroundColor = .black
        window.delegate = self
        view.wantsLayer = true
        view.layer = CALayer()
        view.layer?.magnificationFilter = .nearest
        view.layer?.contentsGravity = .resizeAspect
        view.layer?.backgroundColor = NSColor.black.cgColor
        window.contentView = view
        window.center()
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(view)
        NSApp.activate(ignoringOtherApps: true)
        NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp, .flagsChanged]) { [weak self] e in
            self?.key(e)
            if e.modifierFlags.contains(.command) { return e }
            return nil
        }
        startAudio()
        menu()
        timer = Timer(timeInterval: 1.0 / 240.0, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer!, forMode: .common)
    }

    func parseArgs() {
        let a = CommandLine.arguments
        var i = 1
        while i < a.count {
            switch a[i] {
            case "--frames": maxFrames = Int(a[i + 1]) ?? 0; i += 1
            case "--shot": shotPath = a[i + 1]; i += 1
            case "--save-dir": saveDir = URL(fileURLWithPath: a[i + 1], isDirectory: true); i += 1
            case "--input": scriptText = a[i + 1]; i += 1
            case "--rom": romPath = a[i + 1]; i += 1
            case "--title": titleText = a[i + 1]; i += 1
            default: break
            }
            i += 1
        }
    }

    func parseScript(_ text: String) {
        for item in text.split(separator: ",") {
            let parts = item.split(separator: ":")
            guard parts.count == 2, let f = Int(parts[0]) else { continue }
            var bits: Int64 = 0
            for n in parts[1].split(separator: "+") {
                if let b = game.spec.bits.firstIndex(of: String(n)) { bits |= 1 << Int64(b) }
            }
            script[f, default: 0] |= bits
        }
    }

    func headless() {
        for f in 0..<maxFrames {
            _ = game.step(script[f] ?? 0, 0)
            game.audioN.pointee = 0
        }
        if let p = shotPath {
            let url = URL(fileURLWithPath: p)
            if let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) {
                CGImageDestinationAddImage(dest, game.image(), nil)
                CGImageDestinationFinalize(dest)
            }
        }
        game.finish()
        print("ran \(maxFrames) frames")
        NSApp.terminate(nil)
    }

    func menu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Toggle Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit \(game.spec.title)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        NSApp.mainMenu = main
    }

    func key(_ e: NSEvent) {
        if e.type == .keyDown {
            if e.isARepeat { return }
            if e.keyCode == 3 && !e.modifierFlags.contains(.command) { window.toggleFullScreen(nil); return }
            held.insert(e.keyCode)
        } else if e.type == .keyUp {
            held.remove(e.keyCode)
        }
    }

    func padBits(_ pad: GCExtendedGamepad) -> Int64 {
        let s = game.spec
        var b: Int64 = 0
        func bit(_ n: String) -> Int64 { if let i = s.bits.firstIndex(of: n) { return 1 << Int64(i) } else { return 0 } }
        let x = pad.leftThumbstick.xAxis.value + pad.dpad.xAxis.value
        let y = pad.leftThumbstick.yAxis.value + pad.dpad.yAxis.value
        if x < -0.4 { b |= bit("left") }
        if x > 0.4 { b |= bit("right") }
        if y > 0.4 { b |= bit("up") }
        if y < -0.4 { b |= bit("down") }
        let buttons: [String: GCControllerButtonInput?] = [
            "a": pad.buttonA, "b": pad.buttonB, "x": pad.buttonX, "y": pad.buttonY,
            "leftShoulder": pad.leftShoulder, "rightShoulder": pad.rightShoulder,
            "leftTrigger": pad.leftTrigger, "rightTrigger": pad.rightTrigger, "menu": pad.buttonMenu,
        ]
        for (name, button) in s.gamepad {
            if let bt = buttons[button] ?? nil, bt.isPressed { b |= bit(name) }
        }
        return b
    }

    func inputs() -> (Int64, Int64) {
        var p1: Int64 = 0, p2: Int64 = 0
        for k in held { p1 |= map1[k] ?? 0; p2 |= map2[k] ?? 0 }
        let pads = GCController.controllers().compactMap { $0.extendedGamepad }
        if pads.count > 0 { p1 |= padBits(pads[0]) }
        if pads.count > 1 { p2 |= padBits(pads[1]) }
        return (p1, p2)
    }

    func tick() {
        let now = CACurrentMediaTime()
        acc += now - last
        last = now
        let dt = 1.0 / 60.0
        if acc > 0.25 { acc = dt }
        var ran = false
        while acc >= dt {
            acc -= dt
            let (p1, p2) = inputs()
            if game.step(p1, p2) { NSApp.terminate(nil); return }
            game.drainAudio(into: ring)
            if game.fullscreen.pointee != 0 { game.fullscreen.pointee = 0; window.toggleFullScreen(nil) }
            ran = true
        }
        if ran {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            view.layer?.contents = game.image()
            CATransaction.commit()
        }
    }

    func startAudio() {
        let fmt = AVAudioFormat(standardFormatWithSampleRate: game.spec.audio.rate, channels: 2)!
        let src = AVAudioSourceNode(format: fmt) { [ring] _, _, frameCount, list -> OSStatus in
            let abl = UnsafeMutableAudioBufferListPointer(list)
            let n = Int(frameCount)
            guard abl.count >= 2, let l = abl[0].mData?.assumingMemoryBound(to: Float.self),
                  let r = abl[1].mData?.assumingMemoryBound(to: Float.self) else { return noErr }
            ring.pop(n, l, r)
            return noErr
        }
        engine.attach(src)
        engine.connect(src, to: engine.mainMixerNode, format: fmt)
        try? engine.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ note: Notification) { game?.finish() }
}

let app = NSApplication.shared
let shell = Shell()
app.delegate = shell
app.setActivationPolicy(.regular)
app.run()
