// The arcade's download client, as Foundation and CryptoKit have it (no window, no platform UI): ask the service to
// build a program for this device when its cards changed, fetch the build's manifest, download only the chunks not
// already here (an update reuses every unchanged chunk of the installed build, read back and checked again), check
// every chunk's and every file's SHA-256, assemble the files in a staging folder and swap it in; verify an
// installation against its manifest. The same steps as the Mac's Launcher.swift, for the iOS launcher.

import CryptoKit
import Foundation

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

enum ArcadeError: Error, CustomStringConvertible {
    case message(String)
    var description: String { if case .message(let m) = self { return m }; return "error" }
}

func sha256(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

// an id from the network that becomes a folder or file name here (a program, a cartridge): 1 to 100 of A-Z a-z 0-9
// . _ -, and not "." or ".."
func safeId(_ s: String) -> Bool {
    s != "." && s != ".." && s.range(of: #"\A[A-Za-z0-9._-]{1,100}\z"#, options: .regularExpression) != nil
}

// the arcade service this device talks to: its address and, for a paired device, its token
struct Service {
    var base: URL
    var token: String?

    func url(_ path: String) -> URL {
        URL(string: path.hasPrefix("/") ? String(path.dropFirst()) : path, relativeTo: base)!.absoluteURL
    }

    func request(_ path: String, method: String = "GET", body: Data? = nil, timeout: Double = 30) -> URLRequest {
        var r = URLRequest(url: url(path))
        r.httpMethod = method
        r.timeoutInterval = timeout
        if let t = token { r.setValue("Bearer " + t, forHTTPHeaderField: "Authorization") }
        if let b = body { r.httpBody = b; r.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        return r
    }

    func data(_ path: String, method: String = "GET", body: Data? = nil, timeout: Double = 30) async throws -> (Data, Int, HTTPURLResponse?) {
        let (d, r) = try await URLSession.shared.data(for: request(path, method: method, body: body, timeout: timeout))
        let h = r as? HTTPURLResponse
        return (d, h?.statusCode ?? 0, h)
    }

    func json(_ path: String, method: String = "GET", body: Data? = nil) async throws -> [String: Any] {
        let (d, code, _) = try await data(path, method: method, body: body)
        if code == 401 { throw ArcadeError.message("this device is not paired with the Mac any more") }
        guard code == 200, let o = try JSONSerialization.jsonObject(with: d) as? [String: Any] else {
            throw ArcadeError.message("\(path): \(code)")
        }
        return o
    }

    func alive() async -> Bool {
        (try? await data("api/status", timeout: 2).1) == 200
    }
}

// What an install reports while it runs: (phase, done, total, bytes per second, label)
typealias Progress = (String, Int, Int, Double, String) -> Void

final class Client {
    let service: Service
    let platform: String              // this device's platform key (build.py): the builds it downloads
    let library: URL                  // installed programs, one folder each
    var paused = false
    var cancelled = false
    var bandwidth = 0                 // bytes a second, 0 for no limit

    init(service: Service, platform: String, library: URL) {
        self.service = service
        self.platform = platform
        self.library = library
    }

    func installDir(_ id: String) -> URL? { safeId(id) ? library.appendingPathComponent(id, isDirectory: true) : nil }

    // build on the service if the cards changed since its last build for this platform, then download what is not
    // here yet; returns the installation (play time kept from the one it replaces)
    func install(_ id: String, previous: Installed?, progress: Progress, notice: (String) -> Void) async throws -> Installed {
        guard let dest = installDir(id) else { throw ArcadeError.message("not a program id") }
        let q = "?platform=" + platform
        progress("preparing", 0, 1, 0, "asking the arcade service")
        var entry = try await service.json("api/game/\(id)\(q)")
        if (entry["build_due"] as? Bool) == true {
            _ = try await service.data("api/build/\(id)\(q)", method: "POST")
            while true {
                try await Task.sleep(nanoseconds: 250_000_000)
                let st = try await service.json("api/build/\(id)\(q)")
                let s = st["state"] as? String ?? ""
                progress("building", st["step"] as? Int ?? 0, st["of"] as? Int ?? 6, 0, st["label"] as? String ?? "")
                if s == "done" { break }
                if s == "error" || s == "idle" {          // idle: the service restarted and lost the build
                    let why = st["error"] as? String ?? "the service lost the build"
                    let good = (entry["build"] as? [String: Any])?["build"] as? String
                    if good == nil || good == previous?.build {
                        throw ArcadeError.message("The cards in progress don't build for this device yet (\(why)). "
                                                  + (good == nil ? "There is no earlier build." : "You have the last good build."))
                    }
                    notice("The cards in progress don't build yet: installing the last good build instead.")
                    break
                }
                if cancelled { throw ArcadeError.message("cancelled") }
            }
            entry = try await service.json("api/game/\(id)\(q)")
        }
        guard let build = entry["build"] as? [String: Any], let mpath = build["manifest"] as? String else {
            throw ArcadeError.message("no build to download")
        }
        let (md, mcode, _) = try await service.data(mpath)
        guard mcode == 200 else { throw ArcadeError.message("the build's manifest is not there") }
        let man = try JSONDecoder().decode(Manifest.self, from: md)
        // every file stays inside the staging folder: a relative path with no ".." in it (checked by its parts: a
        // standardized URL drops /private only from paths that exist, so comparing prefixes is not reliable)
        if let f = man.files.first(where: { $0.path.isEmpty || $0.path.hasPrefix("/") || $0.path.split(separator: "/").contains("..") }) {
            throw ArcadeError.message("the build's manifest puts \(f.path) outside the program")
        }
        let staging = library.appendingPathComponent("\(id).staging", isDirectory: true)
        let fm = FileManager.default
        try? fm.removeItem(at: staging)
        try fm.createDirectory(at: staging, withIntermediateDirectories: true)
        // chunks already here: from the installed build's files, if they are intact
        var have: [String: (URL, Int)] = [:]
        if let od = try? Data(contentsOf: dest.appendingPathComponent(".manifest.json")),
           let om = try? JSONDecoder().decode(Manifest.self, from: od), previous?.build != man.build {
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
        progress("downloading", 0, total, 0, "")
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
                    let path = "chunk/\(c.sha256)" + (bandwidth > 0 ? "?rate=\(bandwidth)" : "")
                    let (d, code, _) = try await service.data(path, timeout: 120)
                    guard code == 200, sha256(d) == c.sha256 else {
                        throw ArcadeError.message("chunk \(c.sha256.prefix(12)) failed its check")
                    }
                    part = d
                    done += d.count
                    let now = Date().timeIntervalSince1970
                    window.append((now, done))
                    window = window.filter { now - $0.0 < 1.5 }
                    let rate = window.count > 1 ? Double(done - window[0].1) / max(0.05, now - window[0].0)
                        : Double(done) / max(0.05, now - t0)
                    progress("downloading", done, total, rate, "")
                }
                data.append(part!)
            }
            progress("verifying", done, total, 0, f.path)
            guard sha256(data) == f.sha256 else { throw ArcadeError.message("\(f.path) failed its check") }
            let out = staging.appendingPathComponent(f.path)
            try fm.createDirectory(at: out.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: out)
            if f.executable { try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: out.path) }
        }
        progress("installing", total, total, 0, "")
        try md.write(to: staging.appendingPathComponent(".manifest.json"))
        try? fm.removeItem(at: dest)
        try fm.moveItem(at: staging, to: dest)
        return Installed(version: man.version, build: man.build, size: man.size,
                         installedAt: previous?.installedAt ?? Date().timeIntervalSince1970,
                         playSeconds: previous?.playSeconds ?? 0, lastPlayed: previous?.lastPlayed ?? 0,
                         app: man.app, executable: man.executable, manifest: mpath)
    }

    // every installed file against the manifest: how many fail, of how many (-1: no manifest)
    func verify(_ id: String, progress: Progress) -> (bad: Int, files: Int) {
        guard let dest = installDir(id), let d = try? Data(contentsOf: dest.appendingPathComponent(".manifest.json")),
              let man = try? JSONDecoder().decode(Manifest.self, from: d) else { return (-1, 0) }
        var bad = 0
        for (k, f) in man.files.enumerated() {
            progress("validating", k + 1, man.files.count, 0, f.path)
            let fd = (try? Data(contentsOf: dest.appendingPathComponent(f.path))) ?? Data()
            if sha256(fd) != f.sha256 { bad += 1 }
        }
        return (bad, man.files.count)
    }

    // a cartridge the Mac's library lists: its file, kept in caches (asked again only when the Mac's copy changed)
    func cartridge(_ romId: String, cache: URL) async throws -> URL {
        guard safeId(romId) else { throw ArcadeError.message("not a cartridge id") }
        let fm = FileManager.default
        let dir = cache.appendingPathComponent(romId, isDirectory: true)
        let tagFile = dir.appendingPathComponent(".etag")
        let old = (try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil))?.first { !$0.lastPathComponent.hasPrefix(".") }
        var req = service.request("api/cartridge/\(romId)", timeout: 300)
        if old != nil, let tag = try? String(contentsOf: tagFile, encoding: .utf8) { req.setValue(tag, forHTTPHeaderField: "If-None-Match") }
        let (d, r) = try await URLSession.shared.data(for: req)
        let h = r as? HTTPURLResponse
        if h?.statusCode == 304, let o = old { return o }
        guard h?.statusCode == 200 else { throw ArcadeError.message("the Mac did not send the cartridge (\(h?.statusCode ?? 0))") }
        // the Mac's file name, as one plain name in the cartridge's folder (not "/", ".", "..", hidden or empty)
        let sent = ((h?.value(forHTTPHeaderField: "X-Cartridge-File")?.removingPercentEncoding ?? "") as NSString).lastPathComponent
        let name = sent.isEmpty || sent.hasPrefix(".") || sent.contains("/") ? "\(romId).bin" : sent
        try? fm.removeItem(at: dir)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let out = dir.appendingPathComponent(name)
        try d.write(to: out)
        if let tag = h?.value(forHTTPHeaderField: "ETag") { try? tag.write(to: tagFile, atomically: true, encoding: .utf8) }
        return out
    }
}
