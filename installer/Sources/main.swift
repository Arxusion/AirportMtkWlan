//
//  main.swift
//  AirportMtkWlan Installer v2.2.1
//
//  Copyright © 2026 Aswini Soni (Arxusion). All rights reserved.
//

import SwiftUI
import AppKit

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!

    func applicationDidFinishLaunching(_ aNotification: Notification) {
        let contentView = ContentView()

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 960, height: 680),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.center()
        window.minSize = NSSize(width: 880, height: 600)
        window.title = "AirportMtkWlan Deployment Suite v2.2.1"
        window.titleVisibility = .visible
        window.titlebarAppearsTransparent = false
        window.backgroundColor = NSColor.white
        window.appearance = NSAppearance(named: .aqua)
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: contentView)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
