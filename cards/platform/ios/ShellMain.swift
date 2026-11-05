// A game's own app on iPhone and iPad: one window (a UIScene) playing the bundle it is in (GameShell.swift). With
// --frames it runs headless, prints "ran N frames" and quits: the build's check, through `simctl launch --console`.
// The game's own Quit starts it again from the beginning (an iOS app does not quit itself).

import UIKit

@main
final class ShellApp: UIResponder, UIApplicationDelegate {
    func application(_ app: UIApplication, didFinishLaunchingWithOptions opts: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let o = GameOptions(arguments: CommandLine.arguments)
        if o.frames >= 0 {
            do {
                let g = try Game(bundle: Bundle.main.bundleURL, saveDir: o.saveDir, romPath: o.rom)
                print(g.headless(o))
                g.close()
                exit(0)
            } catch {
                print("error: \(error)")
                exit(1)
            }
        }
        return true
    }

    func application(_ app: UIApplication, configurationForConnecting session: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let c = UISceneConfiguration(name: "Game", sessionRole: session.role)
        c.delegateClass = ShellScene.self
        return c
    }
}

final class ShellScene: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        guard let ws = scene as? UIWindowScene else { return }
        let w = UIWindow(windowScene: ws)
        window = w
        start()
        w.makeKeyAndVisible()
    }

    func start() {
        let vc = GameViewController(bundle: Bundle.main.bundleURL, options: GameOptions(arguments: CommandLine.arguments))
        vc.closable = false
        vc.onExit = { [weak self] _ in DispatchQueue.main.async { self?.start() } }
        window?.rootViewController = vc
    }

    func sceneWillResignActive(_ scene: UIScene) {
        (window?.rootViewController as? GameViewController)?.pause()
    }
}
