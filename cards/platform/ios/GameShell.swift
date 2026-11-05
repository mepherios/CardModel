// The native effect shell for a card-model game on iPhone and iPad (CM21, CM34): the picture, touch controls drawn
// over it, game controllers and keyboards, sound and the save file. It knows nothing about the game. game.json
// (written by `cardmodel arcade build GAME --platform ios` from the game card) says which symbols of
// Frameworks/game.dylib are the frame function, the screen, the sound, the input bits and the save; the game
// decides everything else.
//
// The same file runs in two places: in a game's own app (with ShellMain.swift: the bundle the build makes), and in
// the iOS launcher (cards/app/arcade_ios), which installs a game's bundle and plays it in a GameViewController.
//
//   --frames N          run N frames headless, print "ran N frames" and quit (checks)
//   --shot PATH         with --frames: write the last frame as a PNG
//   --input SCRIPT      frame:button+button,... pressed for one frame each (checks)
//   --save-dir DIR      where save.bin lives (default: the app's Library/Application Support/Cardmodel Arcade/saves/ID)
//   --rom PATH          a cartridge, for a console player (game.json has "cartridge"): a .zip is read in memory
//   --title TEXT        what the player is called while it plays
//   --controls FILE     the player's own controls ({keys, keys2, gamepad}: what the launcher's Controls page writes)
//   --mute              no sound (scripted runs nobody is listening to)

import AVFoundation
import Compression
#if canImport(CoreAudio)
import CoreAudio                               // the audio buffer helpers, on Mac Catalyst
#endif
import GameController
import ImageIO
import UIKit
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
    let keep: [Keep]?              // arrays kept beside the save: bits ORed in ("or"), or set bytes copied ("copy")
    let globals: [String: Int64]?  // Int64 globals set before the module starts
    struct Area: Decodable { let x: Int; let y: Int; let width: Int; let height: Int }
    struct Pointer: Decodable { let x: String; let y: String; let down: String; let area: Area }
    let pointer: Pointer?          // a touch screen: a finger inside area (screen pixels) sets down, x, y
    let clock: String?             // an Int64 the shell keeps at the Unix time (a cartridge's real-time clock)
    let clockOffset: String?       // an Int64 the shell keeps at the local time's offset from UTC, in seconds
    let flush: String?             // called before the shell stops (unsaved battery RAM)
}

// the player's own controls (the launcher's Controls page): any section given replaces the game card's
struct Controls: Decodable {
    let keys: [String: [String]]?
    let keys2: [String: [String]]?
    let gamepad: [String: String]?
}

struct GameOptions {
    var frames = -1
    var shot: String?
    var input = ""
    var saveDir: URL?
    var rom: String?
    var title: String?
    var controls: String?
    var mute = false

    init() {}
    init(arguments a: [String]) {
        var i = 1
        while i < a.count {
            let next = i + 1 < a.count ? a[i + 1] : ""
            switch a[i] {
            case "--frames": frames = Int(next) ?? 0; i += 1
            case "--shot": shot = next; i += 1
            case "--input": input = next; i += 1
            case "--save-dir": saveDir = URL(fileURLWithPath: next, isDirectory: true); i += 1
            case "--rom": rom = next; i += 1
            case "--title": title = next; i += 1
            case "--controls": controls = next; i += 1
            case "--mute": mute = true
            default: break
            }
            i += 1
        }
    }
}

enum ShellError: Error, CustomStringConvertible {
    case message(String)
    var description: String { if case .message(let m) = self { return m }; return "error" }
}

typealias VoidFn = @convention(c) () -> Void
typealias FrameFn = @convention(c) (Int64, Int64) -> Int64
typealias LoadFn = @convention(c) (Int64) -> Void

// a cartridge file's bytes: the file itself, or the first member of a .zip with one of the extensions that fits the
// cartridge array (limit bytes unpacked); every offset the .zip gives is checked against the file
func readCartridge(_ path: String, _ exts: [String], limit: Int) -> Data? {
    guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)), !data.isEmpty else { return nil }
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
        guard o + 46 + nlen <= b.count else { return nil }
        let name = String(decoding: b[(o + 46)..<(o + 46 + nlen)], as: UTF8.self).lowercased()
        o += 46 + nlen + elen + clen
        guard exts.contains(where: { name.hasSuffix($0) }), local + 30 <= b.count, u32(local) == 0x04034b50,
              usize > 0, usize <= limit else { continue }
        let start = local + 30 + u16(local + 26) + u16(local + 28)
        guard start + csize <= b.count else { return nil }
        if method == 0 { return Data(b[start..<(start + csize)]) }
        guard method == 8 else { return nil }
        var out = [UInt8](repeating: 0, count: usize)
        let n = b.withUnsafeBufferPointer { src in
            src.baseAddress.map { compression_decode_buffer(&out, usize, $0 + start, csize, nil, COMPRESSION_ZLIB) } ?? 0
        }
        return n == usize ? Data(out) : nil
    }
    return nil
}

// where a bundle keeps the library and game.json: an iOS bundle is flat (Frameworks/, the rest at its root), a Mac
// Catalyst one has the macOS layout (Contents/Frameworks, Contents/Resources)
func bundleLayout(_ dir: URL) -> (frameworks: URL, resources: URL) {
    let contents = dir.appendingPathComponent("Contents", isDirectory: true)
    if FileManager.default.fileExists(atPath: contents.appendingPathComponent("Info.plist").path) {
        return (contents.appendingPathComponent("Frameworks"), contents.appendingPathComponent("Resources"))
    }
    return (dir.appendingPathComponent("Frameworks"), dir)
}

final class Game {
    let spec: Spec
    let handle: UnsafeMutableRawPointer
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
    var clockOffset: UnsafeMutablePointer<Int64>?
    var flushFn: VoidFn?
    var kept: [(UnsafeMutablePointer<UInt8>, Spec.Keep)] = []
    var touch: (x: UnsafeMutablePointer<Int64>, y: UnsafeMutablePointer<Int64>, down: UnsafeMutablePointer<Int64>)?
    private var closed = false

    // the launcher plays one game after another in its own process: closing a game unloads its library, so the
    // next one (or the same one again) starts from the library's own data, as a fresh process would
    init(bundle dir: URL, saveDir: URL?, romPath: String?) throws {
        let (frameworks, resources) = bundleLayout(dir)
        let specURL = resources.appendingPathComponent("game.json")
        guard let specData = try? Data(contentsOf: specURL) else { throw ShellError.message("no game.json in \(dir.lastPathComponent)") }
        spec = try JSONDecoder().decode(Spec.self, from: specData)
        let saves = saveDir ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cardmodel Arcade/saves/\(spec.id)", isDirectory: true)
        saveURL = saves.appendingPathComponent("save.bin")
        let libPath = frameworks.appendingPathComponent("game.dylib").path
        guard let h = dlopen(libPath, RTLD_NOW | RTLD_LOCAL) else {
            throw ShellError.message("cannot load \(libPath): \(String(cString: dlerror()))")
        }
        handle = h
        var missing: [String] = []
        func sym(_ n: String) -> UnsafeMutableRawPointer {
            if let p = dlsym(h, n) { return p }
            missing.append(n)
            return UnsafeMutableRawPointer(bitPattern: 0x10)!
        }
        frameFn = unsafeBitCast(sym(spec.entry.frame), to: FrameFn.self)
        fb = sym(spec.screen.symbol).assumingMemoryBound(to: UInt8.self)
        audio = sym(spec.audio.symbol).assumingMemoryBound(to: UInt8.self)
        audioN = sym(spec.audio.count).assumingMemoryBound(to: Int64.self)
        save = sym(spec.save.symbol).assumingMemoryBound(to: UInt8.self)
        saveDirty = sym(spec.save.dirty).assumingMemoryBound(to: Int64.self)
        quit = sym(spec.entry.quit).assumingMemoryBound(to: Int64.self)
        fullscreen = sym(spec.entry.fullscreen).assumingMemoryBound(to: Int64.self)
        // every stored constant is set from here on
        let reset = sym(spec.entry.reset), initFn = sym(spec.entry.initFn)
        let cart = spec.cartridge.map { (sym($0.symbol), sym($0.load)) }
        if let c = spec.clock { clock = sym(c).assumingMemoryBound(to: Int64.self) }
        if let c = spec.clockOffset { clockOffset = sym(c).assumingMemoryBound(to: Int64.self) }
        if let f = spec.flush { flushFn = unsafeBitCast(sym(f), to: VoidFn.self) }
        let globals = (spec.globals ?? [:]).map { (sym($0.key), $0.value) }
        for k in spec.keep ?? [] { kept.append((sym(k.symbol).assumingMemoryBound(to: UInt8.self), k)) }
        if let pt = spec.pointer {
            touch = (sym(pt.x).assumingMemoryBound(to: Int64.self), sym(pt.y).assumingMemoryBound(to: Int64.self),
                     sym(pt.down).assumingMemoryBound(to: Int64.self))
        }
        guard missing.isEmpty else {
            dlclose(h)
            throw ShellError.message("game.dylib has no \(missing.joined(separator: ", "))")
        }
        try? FileManager.default.createDirectory(at: saves, withIntermediateDirectories: true)
        unsafeBitCast(reset, to: VoidFn.self)()
        if let c = spec.cartridge, let (array, load) = cart {
            guard let path = romPath ?? c.path else { dlclose(h); throw ShellError.message("\(spec.title) plays a cartridge: start it with one") }
            guard let data = readCartridge(path, c.extensions, limit: c.bytes) else { dlclose(h); throw ShellError.message("cannot read a cartridge from \(path)") }
            let dst = array.assumingMemoryBound(to: UInt8.self)
            let n = min(data.count, c.bytes)
            guard n > 0 else { dlclose(h); throw ShellError.message("an empty cartridge: \(path)") }
            memset(dst, 0, c.bytes)            // the whole array: reset_all leaves it to the host
            data.withUnsafeBytes { raw in if let p = raw.baseAddress { _ = memcpy(dst, p, n) } }
            unsafeBitCast(load, to: LoadFn.self)(Int64(n))
        }
        clock?.pointee = Int64(Date().timeIntervalSince1970)
        clockOffset?.pointee = Int64(TimeZone.current.secondsFromGMT())
        for (p, value) in globals { p.assumingMemoryBound(to: Int64.self).pointee = value }
        if let data = try? Data(contentsOf: saveURL) {
            data.withUnsafeBytes { raw in
                let n = min(raw.count, spec.save.bytes)
                for i in 0..<n { save[i] = raw[i] }
            }
        }
        unsafeBitCast(initFn, to: VoidFn.self)()
    }

    func step(_ p1: Int64, _ p2: Int64) -> Bool {
        clock?.pointee = Int64(Date().timeIntervalSince1970)
        clockOffset?.pointee = Int64(TimeZone.current.secondsFromGMT())
        let q = frameFn(p1, p2)
        if saveDirty.pointee != 0 { writeSave() }
        return q != 0
    }

    // let the module save what it has not, then write it (also when the app leaves the screen: iOS may end it there)
    func flush() {
        flushFn?()
        if saveDirty.pointee != 0 { writeSave() }
    }

    // before closing: the save, then the kept arrays merged into their files
    func finish() {
        flush()
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

    func close() {
        if closed { return }
        closed = true
        dlclose(handle)
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

    func writePNG(_ path: String) -> Bool {
        guard let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL,
                                                         UTType.png.identifier as CFString, 1, nil) else { return false }
        CGImageDestinationAddImage(dest, image(), nil)
        return CGImageDestinationFinalize(dest)
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

    func bit(_ name: String) -> Int64 {
        if let i = spec.bits.firstIndex(of: name) { return 1 << Int64(i) }
        return 0
    }

    // frame:button+button,... (checks)
    func script(_ text: String) -> [Int: Int64] {
        var out: [Int: Int64] = [:]
        for item in text.split(separator: ",") {
            let parts = item.split(separator: ":")
            guard parts.count == 2, let f = Int(parts[0]) else { continue }
            for n in parts[1].split(separator: "+") { out[f, default: 0] |= bit(String(n)) }
        }
        return out
    }

    // a check without a screen: N frames with the script's buttons, the last picture as a PNG, the save kept
    func headless(_ o: GameOptions) -> String {
        let s = script(o.input)
        for f in 0..<max(o.frames, 0) {
            _ = step(s[f] ?? 0, 0)
            audioN.pointee = 0
        }
        var out = "ran \(max(o.frames, 0)) frames"
        if let p = o.shot, !writePNG(p) { out += " (could not write \(p))" }
        finish()
        return out
    }
}

// a ring of stereo samples between the frame loop and the audio thread
final class Ring {
    private var buf: [Float]
    private var r = 0, w = 0
    private let lock = NSLock()
    init(frames: Int) { buf = [Float](repeating: 0, count: frames * 2) }
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
    func clear() { lock.lock(); r = 0; w = 0; lock.unlock() }
}

// key names (game card, the launcher's Controls page) to the keyboard's HID usages (UIKeyboardHIDUsage)
let keyUsages: [String: Int] = {
    var m: [String: Int] = [:]
    for (k, c) in "abcdefghijklmnopqrstuvwxyz".enumerated() { m[String(c)] = 0x04 + k }
    for (k, c) in "1234567890".enumerated() { m[String(c)] = 0x1E + k }
    for k in 1...12 { m["f\(k)"] = 0x3A + k - 1 }
    for k in 1...9 { m["keypad\(k)"] = 0x59 + k - 1 }
    let named: [String: Int] = [
        "return": 0x28, "escape": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C, "minus": 0x2D, "equal": 0x2E,
        "leftbracket": 0x2F, "rightbracket": 0x30, "backslash": 0x31, "semicolon": 0x33, "quote": 0x34, "grave": 0x35,
        "comma": 0x36, "period": 0x37, "slash": 0x38, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
        "keypaddivide": 0x54, "keypadmultiply": 0x55, "keypadminus": 0x56, "keypadplus": 0x57, "keypadenter": 0x58,
        "keypad0": 0x62, "keypaddecimal": 0x63, "control": 0xE0, "shift": 0xE1, "option": 0xE2, "rcontrol": 0xE4,
        "rshift": 0xE5, "roption": 0xE6,
    ]
    m.merge(named) { _, b in b }
    return m
}()

// a controller's buttons by the names game cards use
func padButtons(_ pad: GCExtendedGamepad) -> [String: GCControllerButtonInput?] {
    [
        "a": pad.buttonA, "b": pad.buttonB, "x": pad.buttonX, "y": pad.buttonY,
        "leftShoulder": pad.leftShoulder, "rightShoulder": pad.rightShoulder,
        "leftTrigger": pad.leftTrigger, "rightTrigger": pad.rightTrigger, "menu": pad.buttonMenu,
        "options": pad.buttonOptions, "leftThumbstickButton": pad.leftThumbstickButton,
        "rightThumbstickButton": pad.rightThumbstickButton,
    ]
}

// Touch controls drawn from the game card's input: a pad for the bits named up, down, left and right, and a button
// for every other bit the card gives a controller button, where that button sits on a controller and named after
// the first bit it carries (a button that carries two bits presses both, as the controller's does). Bits with no
// controller button get small buttons of their own. A finger can slide from button to button.
final class TouchControls: UIView {
    struct Control { var bits: Int64; var label: String; var center: CGPoint; var radius: CGFloat; var round: Bool }
    var padBits: (up: Int64, down: Int64, left: Int64, right: Int64) = (0, 0, 0, 0)
    var pad: (center: CGPoint, radius: CGFloat)?
    var controls: [Control] = []
    var held: [ObjectIdentifier: Int64] = [:]
    var bits: Int64 { held.values.reduce(0, |) }
    var others: [(String, Int64)] = []                 // controller button name (or the bit's own) -> bits
    var free: UITouch?                                 // a touch on no control (the touch screen's pointer)
    var onFree: ((UITouch?) -> Void)?
    // put away while a controller or keyboard plays: no buttons drawn or pressed, so every touch is a free one (the
    // touch screen still plays), and lifting it asks for the buttons back (onWake)
    var shown = true { didSet { if !shown { held.removeAll() }; setNeedsDisplay() } }
    var onWake: (() -> Void)?
    var touching: Bool { free != nil || !held.isEmpty }

    init(spec: Spec, gamepad: [String: String]) {
        super.init(frame: .zero)
        isMultipleTouchEnabled = true
        backgroundColor = .clear
        isOpaque = false
        func bit(_ n: String) -> Int64 { if let i = spec.bits.firstIndex(of: n) { return 1 << Int64(i) } else { return 0 } }
        padBits = (bit("up"), bit("down"), bit("left"), bit("right"))
        var byButton: [String: Int64] = [:]
        var order: [String] = []
        for name in spec.bits where !["up", "down", "left", "right"].contains(name) {
            let button = gamepad[name] ?? "bit:" + name
            if byButton[button] == nil { order.append(button); labels[button] = name }
            byButton[button, default: 0] |= bit(name)
        }
        others = order.map { ($0, byButton[$0]!) }
    }
    required init?(coder: NSCoder) { fatalError() }
    var labels: [String: String] = [:]

    // place everything in the space the picture leaves: two clusters (pad left, face buttons right), shoulders above
    // them, the menu buttons between them
    func place(left: CGRect, right: CGRect, middle: CGRect) {
        controls = []
        let r = max(44, min(92, min(left.width, left.height) * 0.36))
        let hasPad = padBits.up | padBits.down | padBits.left | padBits.right != 0
        pad = hasPad ? (CGPoint(x: left.midX, y: left.midY + r * 0.2), r) : nil
        let face = CGPoint(x: right.midX, y: right.midY + r * 0.2)
        let b = r * 0.40, d = r * 0.66
        let spots: [String: CGPoint] = [
            "a": CGPoint(x: face.x, y: face.y + d), "b": CGPoint(x: face.x + d, y: face.y),
            "x": CGPoint(x: face.x - d, y: face.y), "y": CGPoint(x: face.x, y: face.y - d),
        ]
        let shoulderY = min(left.midY, right.midY) - r * 1.25
        var small: [(String, Int64)] = []
        var leftTop = 0, rightTop = 0
        for (button, bits) in others {
            let label = labels[button] ?? button
            if let p = spots[button] {
                controls.append(Control(bits: bits, label: label, center: p, radius: b, round: true))
            } else if button.hasPrefix("left") && !button.hasSuffix("ThumbstickButton") {
                controls.append(Control(bits: bits, label: label,
                                        center: CGPoint(x: left.midX - r * 0.45 + CGFloat(leftTop) * r * 0.95, y: shoulderY),
                                        radius: r * 0.42, round: false))
                leftTop += 1
            } else if button.hasPrefix("right") && !button.hasSuffix("ThumbstickButton") {
                controls.append(Control(bits: bits, label: label,
                                        center: CGPoint(x: right.midX + r * 0.45 - CGFloat(rightTop) * r * 0.95, y: shoulderY),
                                        radius: r * 0.42, round: false))
                rightTop += 1
            } else {
                small.append((label, bits))
            }
        }
        let w = min(88, max(56, middle.width / CGFloat(max(small.count, 1)) - 10))
        for (k, (label, bits)) in small.enumerated() {
            let x = middle.midX + (CGFloat(k) - CGFloat(small.count - 1) / 2) * (w + 10)
            controls.append(Control(bits: bits, label: label, center: CGPoint(x: x, y: middle.maxY - 26), radius: w / 2,
                                    round: false))
        }
        setNeedsDisplay()
    }

    func hit(_ p: CGPoint) -> Int64? {
        guard shown else { return nil }
        if let pd = pad {
            let dx = p.x - pd.center.x, dy = p.y - pd.center.y
            let dist = (dx * dx + dy * dy).squareRoot()
            if dist <= pd.radius * 1.15 {
                if dist < pd.radius * 0.18 { return 0 }
                var out: Int64 = 0
                let a = atan2(-dy, dx)                    // eight directions, 45 degrees each
                let s = CGFloat.pi / 8
                if a > -3 * s && a < 3 * s { out |= padBits.right }
                if a > 5 * s || a < -5 * s { out |= padBits.left }
                if a > s && a < 7 * s { out |= padBits.up }
                if a < -s && a > -7 * s { out |= padBits.down }
                return out
            }
        }
        for c in controls {
            if c.round {
                let dx = p.x - c.center.x, dy = p.y - c.center.y
                if dx * dx + dy * dy <= c.radius * c.radius * 1.3 { return c.bits }
            } else if abs(p.x - c.center.x) <= c.radius * 1.05 && abs(p.y - c.center.y) <= 24 {
                return c.bits
            }
        }
        return nil
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if let b = hit(t.location(in: self)) { held[ObjectIdentifier(t)] = b }
            else if free == nil { free = t; onFree?(t) }
        }
        setNeedsDisplay()
    }
    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            if t === free { onFree?(t); continue }
            if held[ObjectIdentifier(t)] != nil { held[ObjectIdentifier(t)] = hit(t.location(in: self)) ?? 0 }
        }
        setNeedsDisplay()
    }
    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            held[ObjectIdentifier(t)] = nil
            if t === free { free = nil; onFree?(nil) }
        }
        if !shown && free == nil { onWake?() }     // on lifting: the picture moves when they come back
        setNeedsDisplay()
    }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { touchesEnded(touches, with: event) }

    override func draw(_ rect: CGRect) {
        guard shown else { return }
        let now = bits
        let line = UIColor(white: 1, alpha: 0.42), fill = UIColor(white: 1, alpha: 0.10), on = UIColor(white: 1, alpha: 0.38)
        if let pd = pad {
            let c = pd.center, r = pd.radius
            let ring = UIBezierPath(ovalIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
            fill.setFill(); ring.fill()
            line.setStroke(); ring.lineWidth = 1.5; ring.stroke()
            let arms: [(Int64, CGFloat, CGFloat)] = [(padBits.up, 0, -1), (padBits.down, 0, 1), (padBits.left, -1, 0), (padBits.right, 1, 0)]
            for (b, dx, dy) in arms {
                let tip = CGPoint(x: c.x + dx * r * 0.78, y: c.y + dy * r * 0.78)
                let base = CGPoint(x: c.x + dx * r * 0.42, y: c.y + dy * r * 0.42)
                let tri = UIBezierPath()
                tri.move(to: tip)
                tri.addLine(to: CGPoint(x: base.x + dy * r * 0.2, y: base.y + dx * r * 0.2))
                tri.addLine(to: CGPoint(x: base.x - dy * r * 0.2, y: base.y - dx * r * 0.2))
                tri.close()
                (now & b != 0 ? UIColor(white: 1, alpha: 0.85) : line).setFill()
                tri.fill()
            }
        }
        for c in controls {
            let pressed = now & c.bits == c.bits && c.bits != 0
            let r = c.radius
            let path = c.round ? UIBezierPath(ovalIn: CGRect(x: c.center.x - r, y: c.center.y - r, width: 2 * r, height: 2 * r))
                : UIBezierPath(roundedRect: CGRect(x: c.center.x - r, y: c.center.y - 17, width: 2 * r, height: 34), cornerRadius: 17)
            (pressed ? on : fill).setFill(); path.fill()
            line.setStroke(); path.lineWidth = 1.5; path.stroke()
            let text = c.label.count <= 2 ? c.label.uppercased() : c.label
            let size: CGFloat = c.round ? min(17, max(10, r * 0.42)) : 13
            let attrs: [NSAttributedString.Key: Any] = [.font: UIFont.systemFont(ofSize: size, weight: .semibold),
                                                        .foregroundColor: UIColor(white: 1, alpha: pressed ? 1 : 0.8)]
            let s = (text as NSString).size(withAttributes: attrs)
            (text as NSString).draw(at: CGPoint(x: c.center.x - s.width / 2, y: c.center.y - s.height / 2), withAttributes: attrs)
        }
    }
}

final class ScreenView: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .black
        layer.magnificationFilter = .nearest
        layer.contentsGravity = .resize
        isUserInteractionEnabled = false
    }
    required init?(coder: NSCoder) { fatalError() }
}

// A game playing: the picture, the touch controls, the keyboard and controllers, the sound, the frame clock.
final class GameViewController: UIViewController {
    let bundleDir: URL
    let options: GameOptions
    var game: Game?
    var onExit: ((String?) -> Void)?          // closed, or quit by the game (an error message when it could not start)
    var closable = true                       // a close button (the launcher's; a game's own app has nowhere to go)
    let screen = ScreenView()
    var touch: TouchControls?
    let closeButton = UIButton(type: .system)
    let ring = Ring(frames: 48000)
    let engine = AVAudioEngine()
    var link: CADisplayLink?
    var last = CACurrentMediaTime()
    var acc = 0.0
    var held = Set<Int>()
    var map1: [Int: Int64] = [:]
    var map2: [Int: Int64] = [:]
    var gamepadMap: [String: String] = [:]
    var pointerAt: (Int64, Int64, Int64) = (0, 0, 0)
    var failed: String?

    init(bundle: URL, options: GameOptions) {
        bundleDir = bundle
        self.options = options
        super.init(nibName: nil, bundle: nil)
        modalPresentationStyle = .fullScreen
    }
    required init?(coder: NSCoder) { fatalError() }

    override var prefersStatusBarHidden: Bool { true }
    override var prefersHomeIndicatorAutoHidden: Bool { true }
    override var preferredScreenEdgesDeferringSystemGestures: UIRectEdge { .all }
    override var canBecomeFirstResponder: Bool { true }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        view.addSubview(screen)
        do {
            game = try Game(bundle: bundleDir, saveDir: options.saveDir, romPath: options.rom)
        } catch {
            failed = "\(error)"
            return
        }
        let s = game!.spec
        var own: Controls?
        if let cp = options.controls, let d = try? Data(contentsOf: URL(fileURLWithPath: cp)) {
            own = try? JSONDecoder().decode(Controls.self, from: d)
        }
        gamepadMap = own?.gamepad ?? s.gamepad
        for (name, keys) in own?.keys ?? s.keys { let b = game!.bit(name); for k in keys { if let c = keyUsages[k] { map1[c, default: 0] |= b } } }
        for (name, keys) in own?.keys2 ?? s.keys2 { let b = game!.bit(name); for k in keys { if let c = keyUsages[k] { map2[c, default: 0] |= b } } }
        let t = TouchControls(spec: s, gamepad: gamepadMap)
        t.onFree = { [weak self] touch in self?.pointer(touch) }
        t.onWake = { [weak self] in self?.showTouch(true) }
        view.addSubview(t)
        touch = t
        if closable {
            closeButton.setImage(UIImage(systemName: "xmark.circle.fill"), for: .normal)
            closeButton.tintColor = UIColor(white: 1, alpha: 0.55)
            closeButton.accessibilityLabel = "Close \(options.title ?? s.title)"
            closeButton.addTarget(self, action: #selector(close), for: .touchUpInside)
            view.addSubview(closeButton)
        }
        controllersChanged()
        NotificationCenter.default.addObserver(self, selector: #selector(controllersChanged), name: .GCControllerDidConnect, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(controllersChanged), name: .GCControllerDidDisconnect, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(pause), name: UIApplication.willResignActiveNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(resume), name: UIApplication.didBecomeActiveNotification, object: nil)
        if !options.mute {
            startAudio()
            NotificationCenter.default.addObserver(self, selector: #selector(audioInterrupted(_:)), name: AVAudioSession.interruptionNotification, object: nil)
            NotificationCenter.default.addObserver(self, selector: #selector(audioRouteChanged), name: .AVAudioEngineConfigurationChange, object: engine)
        }
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        if let f = failed {
            let a = UIAlertController(title: "Could not start", message: f, preferredStyle: .alert)
            if closable { a.addAction(UIAlertAction(title: "OK", style: .default) { [weak self] _ in self?.onExit?(f) }) }
            present(a, animated: true)
            return
        }
        becomeFirstResponder()
        resume()
    }

    // the picture as large as it fits; on a screen taller than wide it sits at the top and the controls below it,
    // otherwise in the middle with the controls on either side (over the picture where the sides are narrow)
    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        guard let s = game?.spec else { return }
        let safe = view.bounds.inset(by: view.safeAreaInsets)
        let aspect = CGFloat(s.screen.width) / CGFloat(s.screen.height)
        let pads = touch?.shown ?? false
        var pic: CGRect
        if safe.height > safe.width && pads {
            let room = max(safe.height * 0.34, 230)
            var w = safe.width, h = w / aspect
            if h > safe.height - room { h = max(safe.height - room, safe.height * 0.4); w = h * aspect }
            pic = CGRect(x: safe.midX - w / 2, y: safe.minY + 8, width: w, height: h)
            let below = CGRect(x: safe.minX, y: pic.maxY, width: safe.width, height: safe.maxY - pic.maxY)
            touch?.frame = view.bounds
            touch?.place(left: CGRect(x: below.minX, y: below.minY, width: below.width / 2, height: below.height - 30),
                         right: CGRect(x: below.midX, y: below.minY, width: below.width / 2, height: below.height - 30),
                         middle: CGRect(x: below.minX + below.width * 0.25, y: below.minY, width: below.width * 0.5, height: below.height))
        } else {
            var h = safe.height, w = h * aspect
            if w > safe.width { w = safe.width; h = w / aspect }
            pic = CGRect(x: safe.midX - w / 2, y: safe.midY - h / 2, width: w, height: h)
            let side = max((safe.width - w) / 2, min(safe.width * 0.22, 220))
            touch?.frame = view.bounds
            touch?.place(left: CGRect(x: safe.minX, y: safe.midY - 40, width: side, height: safe.height / 2 + 40),
                         right: CGRect(x: safe.maxX - side, y: safe.midY - 40, width: side, height: safe.height / 2 + 40),
                         middle: CGRect(x: safe.minX + side, y: safe.maxY - 60, width: safe.width - 2 * side, height: 60))
        }
        screen.frame = pic.integral
        closeButton.frame = CGRect(x: safe.minX + 6, y: safe.minY + 6, width: 44, height: 44)
        if let t = touch { view.bringSubviewToFront(t) }
        view.bringSubviewToFront(closeButton)
    }

    // the touch controls give way to a controller once it is used (one only connected may sit unused), and come
    // back when the last one goes or the screen is touched; they never go while a finger is down (it would lose its
    // button, and the picture would move under it)
    @objc func controllersChanged() {
        if !GCController.controllers().contains(where: { $0.extendedGamepad != nil }) { showTouch(true) }
    }

    func showTouch(_ on: Bool) {
        guard let t = touch, t.shown != on, on || !t.touching else { return }
        t.shown = on
        view.setNeedsLayout()
    }

    // a touch on no control: on a game with a touch screen, where it is on the picture, in the screen's pixels
    func pointer(_ t: UITouch?) {
        guard let s = game?.spec, let pt = s.pointer else { return }
        guard let t = t else { pointerAt.2 = 0; return }
        let p = t.location(in: screen)
        let px = Int(p.x / screen.bounds.width * CGFloat(s.screen.width))
        let py = Int(p.y / screen.bounds.height * CGFloat(s.screen.height))
        let a = pt.area
        if px >= a.x && px < a.x + a.width && py >= a.y && py < a.y + a.height {
            pointerAt = (Int64(px - a.x), Int64(py - a.y), 1)
        } else {
            pointerAt.2 = 0
        }
    }

    override func pressesBegan(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        var mine = false
        for p in presses { if let k = p.key { held.insert(k.keyCode.rawValue); mine = mine || map1[k.keyCode.rawValue] != nil || map2[k.keyCode.rawValue] != nil } }
        if mine { showTouch(false) } else { super.pressesBegan(presses, with: event) }
    }
    override func pressesEnded(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        for p in presses { if let k = p.key { held.remove(k.keyCode.rawValue) } }
        super.pressesEnded(presses, with: event)
    }
    override func pressesCancelled(_ presses: Set<UIPress>, with event: UIPressesEvent?) {
        for p in presses { if let k = p.key { held.remove(k.keyCode.rawValue) } }
        super.pressesCancelled(presses, with: event)
    }

    func padBits(_ pad: GCExtendedGamepad) -> Int64 {
        guard let g = game else { return 0 }
        var b: Int64 = 0
        let x = pad.leftThumbstick.xAxis.value + pad.dpad.xAxis.value
        let y = pad.leftThumbstick.yAxis.value + pad.dpad.yAxis.value
        if x < -0.4 { b |= g.bit("left") }
        if x > 0.4 { b |= g.bit("right") }
        if y > 0.4 { b |= g.bit("up") }
        if y < -0.4 { b |= g.bit("down") }
        let buttons = padButtons(pad)
        for (name, button) in gamepadMap {
            if let bt = buttons[button] ?? nil, bt.isPressed { b |= g.bit(name) }
        }
        return b
    }

    func inputs() -> (Int64, Int64) {
        var p1: Int64 = 0, p2: Int64 = 0
        for k in held { p1 |= map1[k] ?? 0; p2 |= map2[k] ?? 0 }
        let pads = GCController.controllers().compactMap { $0.extendedGamepad }
        let b1 = pads.count > 0 ? padBits(pads[0]) : 0, b2 = pads.count > 1 ? padBits(pads[1]) : 0
        if b1 | b2 != 0 { showTouch(false) }
        p1 |= b1
        p2 |= b2
        if let t = touch, t.shown { p1 |= t.bits }
        return (p1, p2)
    }

    @objc func tick() {
        guard let g = game else { return }
        let now = CACurrentMediaTime()
        acc += now - last
        last = now
        let dt = 1.0 / 60.0
        if acc > 0.25 { acc = dt }
        // the display's ticks wander around 1/60 s: within 2 ms of a frame is a frame (not one dropped, then two),
        // and at most four a tick (a stall is caught up over the next ticks)
        var ran = 0
        while acc >= dt - 0.002 && ran < 4 {
            acc -= dt
            let (p1, p2) = inputs()
            if let t = g.touch { t.x.pointee = pointerAt.0; t.y.pointee = pointerAt.1; t.down.pointee = pointerAt.2 }
            if g.step(p1, p2) { close(); return }
            g.drainAudio(into: ring)
            g.fullscreen.pointee = 0               // always the whole screen here
            ran += 1
        }
        if ran > 0 {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            screen.layer.contents = g.image()
            CATransaction.commit()
        }
    }

    @objc func pause() {
        link?.invalidate()
        link = nil
        game?.flush()
    }

    @objc func resume() {
        guard game != nil, link == nil, view.window != nil else { return }
        last = CACurrentMediaTime()
        acc = 0
        let l = CADisplayLink(target: self, selector: #selector(tick))
        l.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 60, preferred: 60)
        l.add(to: .main, forMode: .common)
        link = l
        restartAudio()
    }

    func startAudio() {
        guard let g = game else { return }
        try? AVAudioSession.sharedInstance().setCategory(.ambient)
        try? AVAudioSession.sharedInstance().setActive(true)
        let fmt = AVAudioFormat(standardFormatWithSampleRate: g.spec.audio.rate, channels: 2)!
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

    // the engine stops for a call, an alarm or Siri (an interruption) and for a new route (headphones, AirPlay): it
    // starts again when that is over, or when the game comes back to the screen (these arrive on any thread)
    @objc nonisolated func audioInterrupted(_ n: Notification) {
        guard (n.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt) == AVAudioSession.InterruptionType.ended.rawValue else { return }
        DispatchQueue.main.async { [weak self] in self?.restartAudio() }
    }
    @objc nonisolated func audioRouteChanged() { DispatchQueue.main.async { [weak self] in self?.restartAudio() } }

    func restartAudio() {
        guard game != nil, link != nil, !options.mute, !engine.isRunning else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        try? engine.start()
    }

    // stop playing: the save written, the sound and the clock stopped, the library unloaded
    @objc func close() {
        pause()
        engine.stop()
        ring.clear()
        NotificationCenter.default.removeObserver(self)
        if let g = game {
            g.finish()
            g.close()
        }
        game = nil
        onExit?(nil)
    }
}
