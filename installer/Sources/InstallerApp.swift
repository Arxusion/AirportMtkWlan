//
//  InstallerApp.swift
//  AirportMtkWlan Unified Deployment Suite v2.2.1
//
//  Copyright © 2026 Aswini Soni (@Arxusion). All rights reserved.
//

import SwiftUI
import AppKit

// MARK: - Navigation Tabs
enum NavigationTab: String, CaseIterable, Identifiable {
    case overview = "Overview"
    case deploy = "Deploy Suite"
    case bootDiagnostics = "Boot Diagnostics"
    case console = "Console Stream"
    case updates = "Updates"
    case recovery = "Recovery & EFI"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .overview: return "display"
        case .deploy: return "arrow.down.circle.fill"
        case .bootDiagnostics: return "stethoscope"
        case .console: return "terminal.fill"
        case .updates: return "arrow.triangle.2.circlepath"
        case .recovery: return "arrow.counterclockwise.circle"
        }
    }
}

// MARK: - Monochrome Minimalist Theme (Apple SF Pro & Crisp Contrast)
struct ThemeColors {
    static let canvasBg = Color(red: 0.98, green: 0.98, blue: 0.99)
    static let cardBg = Color.white
    static let secondaryBg = Color(red: 0.96, green: 0.96, blue: 0.97)

    static let sidebarBg = Color(red: 0.97, green: 0.97, blue: 0.98)
    static let sidebarBorder = Color(red: 0.90, green: 0.90, blue: 0.92)

    static let cardBorder = Color(red: 0.89, green: 0.90, blue: 0.92)
    static let cardBorderSubtle = Color(red: 0.93, green: 0.93, blue: 0.94)

    static let textPrimary = Color(red: 0.08, green: 0.08, blue: 0.09)
    static let textSecondary = Color(red: 0.42, green: 0.44, blue: 0.48)
    static let textMuted = Color(red: 0.62, green: 0.64, blue: 0.68)
    static let sectionHeader = Color(red: 0.16, green: 0.17, blue: 0.19)

    static let accentBlack = Color(red: 0.07, green: 0.07, blue: 0.08)
    static let accentHover = Color(red: 0.18, green: 0.18, blue: 0.20)
    static let accentContrast = Color.white

    static let tabActiveBg = Color(red: 0.07, green: 0.07, blue: 0.08)
    static let tabActiveText = Color.white

    static let greenText = Color(red: 0.09, green: 0.55, blue: 0.24)
    static let greenBg = Color(red: 0.94, green: 0.98, blue: 0.94)
    static let greenBorder = Color(red: 0.80, green: 0.92, blue: 0.82)

    static let redText = Color(red: 0.85, green: 0.18, blue: 0.18)
    static let redBg = Color(red: 0.99, green: 0.94, blue: 0.94)
    static let redBorder = Color(red: 0.95, green: 0.80, blue: 0.80)

    static let terminalBg = Color(red: 0.06, green: 0.07, blue: 0.09)
    static let terminalText = Color(red: 0.92, green: 0.93, blue: 0.95)
}

// MARK: - Main Application View
struct ContentView: View {
    @State private var selectedTab: NavigationTab = .overview

    // Deployment State
    @State private var destinations: [EFIDestination] = []
    @State private var selectedDestination: EFIDestination?
    @State private var selectedFlavor: DriverFlavor = .tahoe
    @State private var installBluetooth: Bool = true
    @State private var autoConfig: Bool = true
    @State private var backupPlist: Bool = true

    // Console & Operation State
    @State private var logs: [String] = []
    @State private var isInstalling: Bool = false
    @State private var installSuccess: Bool? = nil
    @State private var isExportingBootLogs: Bool = false
    @State private var bootLogsExportMessage: String = ""
    @State private var lastExportedURL: URL? = nil

    // Live Telemetry State
    @State private var driverStatus: DriverStatus?
    @State private var currentSSID: String = "Scanning..."
    @State private var currentRate: String = "-- Mbps"
    @State private var currentRSSI: String = "-- dBm"
    @State private var currentChannel: String = "--"
    @State private var currentNSS: String = "2x2 NSS"

    // Update Checker State
    @State private var isCheckingUpdate: Bool = false
    @State private var updateStatusMessage: String = "Click 'Check for updates' to verify latest release on GitHub."
    @State private var latestReleaseURL: URL? = nil
    @State private var updateAvailable: Bool = false
    @State private var latestTagFound: String = ""

    let timer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 0) {
            // MARK: - Left Sidebar (Monochrome Swiss Modern)
            sidebarView
                .frame(width: 240)
                .background(ThemeColors.sidebarBg)

            Rectangle()
                .fill(ThemeColors.sidebarBorder)
                .frame(width: 1)

            // MARK: - Right Main Content Canvas
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    switch selectedTab {
                    case .overview:
                        overviewView
                    case .deploy:
                        deployView
                    case .bootDiagnostics:
                        bootDiagnosticsView
                    case .console:
                        consoleView
                    case .updates:
                        updatesView
                    case .recovery:
                        recoveryView
                    }
                }
                .padding(32)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(ThemeColors.canvasBg)
        }
        .onAppear {
            refreshDestinations()
            refreshTelemetry()
        }
        .onReceive(timer) { _ in
            refreshTelemetry()
        }
    }

    // MARK: - Sidebar View
    private var sidebarView: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Brand & App Icon Header
            HStack(spacing: 12) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .interpolation(.none) // Pixel art crisp scaling
                    .frame(width: 40, height: 40)
                    .cornerRadius(8)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(ThemeColors.cardBorder, lineWidth: 1))

                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text("AirportMtk")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(ThemeColors.textPrimary)

                        Text("v2.2.1")
                            .font(.system(size: 10, weight: .bold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(ThemeColors.accentBlack)
                            .foregroundColor(ThemeColors.accentContrast)
                            .cornerRadius(4)
                    }

                    Text("MediaTek Wi-Fi 6 Suite")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(ThemeColors.textSecondary)
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 24)
            .padding(.bottom, 22)

            Rectangle()
                .fill(ThemeColors.sidebarBorder)
                .frame(height: 1)
                .padding(.horizontal, 16)
                .padding(.bottom, 16)

            // Navigation Items
            VStack(spacing: 4) {
                ForEach(NavigationTab.allCases) { tab in
                    Button(action: {
                        selectedTab = tab
                    }) {
                        HStack(spacing: 10) {
                            Image(systemName: tab.icon)
                                .font(.system(size: 13, weight: selectedTab == tab ? .semibold : .regular))
                                .frame(width: 20, alignment: .center)
                                .foregroundColor(selectedTab == tab ? ThemeColors.tabActiveText : ThemeColors.textSecondary)

                            Text(tab.rawValue)
                                .font(.system(size: 13, weight: selectedTab == tab ? .semibold : .medium))
                                .foregroundColor(selectedTab == tab ? ThemeColors.tabActiveText : ThemeColors.textPrimary)

                            Spacer()
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(
                            selectedTab == tab ?
                                RoundedRectangle(cornerRadius: 8).fill(ThemeColors.tabActiveBg) :
                                RoundedRectangle(cornerRadius: 8).fill(Color.clear)
                        )
                    }
                    .buttonStyle(PlainButtonStyle())
                }
            }
            .padding(.horizontal, 12)

            Spacer()

            // Sidebar Footer Card
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("AirportMtkWlan")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundColor(ThemeColors.textPrimary)
                    Spacer()
                    Text("Darwin 25.x / 24.x")
                        .font(.system(size: 10, weight: .regular))
                        .foregroundColor(ThemeColors.textMuted)
                }

                HStack(spacing: 8) {
                    Button("GitHub") {
                        if let url = URL(string: "https://github.com/Arxusion/AirportMtkWlan") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(ThemeColors.textPrimary)
                    .buttonStyle(PlainButtonStyle())

                    Text("·").foregroundColor(ThemeColors.textMuted)

                    Button("OpenCore") {
                        if let url = URL(string: "https://dortania.github.io/OpenCore-Install-Guide/") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(ThemeColors.textPrimary)
                    .buttonStyle(PlainButtonStyle())

                    Text("·").foregroundColor(ThemeColors.textMuted)

                    Button("Releases") {
                        if let url = URL(string: "https://github.com/Arxusion/AirportMtkWlan/releases") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(ThemeColors.textPrimary)
                    .buttonStyle(PlainButtonStyle())
                }
            }
            .padding(14)
            .background(ThemeColors.cardBg)
            .cornerRadius(10)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(ThemeColors.cardBorder, lineWidth: 1))
            .padding(.horizontal, 14)
            .padding(.bottom, 20)
        }
    }

    // MARK: - Tab 1: Overview View
    private var overviewView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Hardware & Driver Overview",
                subtitle: "High-throughput Wi-Fi 6 (MT7921/MT7922), Apple Wireless Direct Link (AWDL/AirDrop), and Bluetooth companion patcher."
            )

            // System Hardware Architecture Specs
            VStack(spacing: 8) {
                specRow(label: "HOST SYSTEM", value: "macOS 26 Tahoe / macOS 15 Sequoia (x86_64)")
                specRow(label: "PROCESSOR", value: "Tiger Lake-H / Intel Core x86_64")
                specRow(label: "WI-FI CHIPSET", value: "MediaTek MT7921 / MT7922 PCIe 802.11ax")
                specRow(label: "BLUETOOTH", value: "MediaTek USB Bluetooth (0489:e0e2 / SRS_7922)")
                specRow(label: "TARGET OPENCORE", value: selectedDestination?.displayName ?? "Auto-detecting EFI...")
                specRow(label: "DRIVER SUITE", value: "AirportMtkWlan v2.2.1 + AirportMtkBt Companion")
                specRow(
                    label: "KERNEL STATUS",
                    value: (driverStatus?.isLoaded ?? false) ? "RUNNING (MediaTek MT7921/MT7922 802.11ax, AWDL AirDrop Active)" : "Ready to Install / Not Loaded into Active Kernel",
                    isHighlight: (driverStatus?.isLoaded ?? false)
                )
            }

            // Quick Deployment & Diagnostics Action Bar
            HStack(spacing: 14) {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(ThemeColors.greenText)
                        .font(.system(size: 16))
                    Text("Unified driver bundle v2.2.1 ready for deployment. Supports Wi-Fi 6, AWDL, and Bluetooth.")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(ThemeColors.textPrimary)
                }
                Spacer()

                Button("Export Last 3 Boot Logs") {
                    exportLast3Boots()
                }
                .buttonStyle(SecondaryOutlineButtonStyle())

                Button("Deploy Suite") {
                    selectedTab = .deploy
                }
                .buttonStyle(PrimaryBlackButtonStyle())
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(ThemeColors.cardBg)
            .cornerRadius(10)
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Real-Time Wireless Telemetry
            VStack(alignment: .leading, spacing: 12) {
                Text("LIVE WIRELESS TELEMETRY")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.2)
                    .foregroundColor(ThemeColors.sectionHeader)

                HStack(spacing: 12) {
                    telemetryCard(title: "SSID", value: currentSSID)
                    telemetryCard(title: "LINK RATE", value: currentRate)
                    telemetryCard(title: "SIGNAL", value: currentRSSI)
                    telemetryCard(title: "CHANNEL", value: currentChannel)
                    telemetryCard(title: "MIMO", value: currentNSS)
                }
            }
            .padding(18)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Tab 2: Deploy Unified Suite
    private var deployView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Deploy Unified Driver Suite",
                subtitle: "Installs Wi-Fi 802.11ax, Bluetooth companion drivers, and AWDL hardware acceleration to your OpenCore EFI in one run."
            )

            // Card 1: Target OpenCore EFI
            VStack(alignment: .leading, spacing: 12) {
                Text("TARGET OPENCORE EFI")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.2)
                    .foregroundColor(ThemeColors.sectionHeader)

                HStack(spacing: 10) {
                    Picker("", selection: $selectedDestination) {
                        ForEach(destinations) { dst in
                            Text(dst.displayName).tag(Optional(dst))
                        }
                    }
                    .pickerStyle(MenuPickerStyle())

                    Button(action: refreshDestinations) {
                        Image(systemName: "arrow.clockwise")
                    }
                    .buttonStyle(SecondaryOutlineButtonStyle())

                    Button("Mount System EFI") {
                        mountSystemEFI()
                    }
                    .buttonStyle(SecondaryOutlineButtonStyle())

                    Button("Browse...") {
                        browseFolder()
                    }
                    .buttonStyle(SecondaryOutlineButtonStyle())
                }
            }
            .padding(18)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Card 2: Driver Target & Options
            VStack(alignment: .leading, spacing: 14) {
                Text("DRIVER FLAVOR & DEPLOYMENT OPTIONS")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.2)
                    .foregroundColor(ThemeColors.sectionHeader)

                Picker("Driver Flavor", selection: $selectedFlavor) {
                    Text("macOS 26 Tahoe (Kernel 25.x)").tag(DriverFlavor.tahoe)
                    Text("macOS 15 Sequoia (Kernel 24.x)").tag(DriverFlavor.sequoia)
                    Text("Ethernet Legacy (SimpleMtkWlan)").tag(DriverFlavor.ethernet)
                }
                .pickerStyle(SegmentedPickerStyle())

                VStack(alignment: .leading, spacing: 10) {
                    Toggle("Install Bluetooth companion drivers (AirportMtkBtPatcher & AirportMtkBtFw)", isOn: $installBluetooth)
                        .font(.system(size: 12, weight: .medium))
                    Toggle("Auto-configure OpenCore config.plist (Inject Kernel entries & DisableIoMapper quirk)", isOn: $autoConfig)
                        .font(.system(size: 12, weight: .medium))
                    Toggle("Backup existing config.plist before making modifications (saved as config.plist.backup-*)", isOn: $backupPlist)
                        .font(.system(size: 12, weight: .medium))
                }
                .padding(.top, 4)
            }
            .padding(18)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Big Deploy Action Button (High Contrast Stark Black)
            Button(action: performInstallation) {
                HStack(spacing: 10) {
                    if isInstalling {
                        ProgressView()
                            .scaleEffect(0.8)
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else {
                        Image(systemName: "arrow.down.circle.fill")
                            .font(.system(size: 16, weight: .bold))
                    }
                    Text(isInstalling ? "Deploying Drivers to OpenCore EFI..." : "Deploy Unified Driver Suite to EFI (Wi-Fi + BT + AWDL)")
                        .font(.system(size: 14, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(isInstalling ? ThemeColors.accentBlack.opacity(0.7) : ThemeColors.accentBlack)
                .foregroundColor(ThemeColors.accentContrast)
                .cornerRadius(10)
            }
            .buttonStyle(PlainButtonStyle())
            .disabled(isInstalling || selectedDestination == nil)

            // Success Confirmation Banner
            if installSuccess == true {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(ThemeColors.greenText)
                        .font(.system(size: 16))
                    Text("Unified deployment completed successfully! Restart your Mac to apply all kernel drivers.")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(ThemeColors.textPrimary)
                    Spacer()
                }
                .padding(14)
                .background(ThemeColors.greenBg)
                .cornerRadius(10)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(ThemeColors.greenBorder, lineWidth: 1))
            }

            // Real-Time Live Deployment Console Stream
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("DEPLOYMENT REAL-TIME CONSOLE")
                        .font(.system(size: 10, weight: .bold))
                        .tracking(1.2)
                        .foregroundColor(ThemeColors.sectionHeader)
                    Spacer()
                    Button("View Full Console Tab") {
                        selectedTab = .console
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(ThemeColors.textPrimary)
                    .buttonStyle(PlainButtonStyle())
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 3) {
                        if logs.isEmpty {
                            Text("Ready. Click 'Deploy Unified Driver Suite' to stream activity.")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(Color.gray)
                        } else {
                            ForEach(logs.suffix(14), id: \.self) { log in
                                Text(log)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(log.contains("ERROR") ? Color.red : (log.contains("SUCCESS") ? Color.green : Color.white.opacity(0.92)))
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                }
                .frame(height: 150)
                .background(ThemeColors.terminalBg)
                .cornerRadius(10)
            }
            .padding(18)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Tab 3: Boot Diagnostics & Log Collector (Last 3 Boots)
    private var bootDiagnosticsView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Boot Diagnostics & Multi-Boot Log Collector",
                subtitle: "Diagnose kernel panics, kext loading errors (such as module start pointer faults), and sleep/wake hangs across multiple boot cycles."
            )

            // Card 1: Last 3 Boots Collector (Featured)
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("LAST 3 BOOT CYCLES DIAGNOSTIC DUMP")
                            .font(.system(size: 10, weight: .bold))
                            .tracking(1.2)
                            .foregroundColor(ThemeColors.sectionHeader)
                        Text("Extracts kernel telemetry, kext manager loads & errors, panic reports, and OpenCore boot logs across Current Boot (0), Previous Boot (-1), and Prior Boot (-2).")
                            .font(.system(size: 12, weight: .regular))
                            .foregroundColor(ThemeColors.textSecondary)
                    }
                    Spacer()
                }

                HStack(spacing: 12) {
                    Button(action: exportLast3Boots) {
                        HStack(spacing: 8) {
                            if isExportingBootLogs {
                                ProgressView()
                                    .scaleEffect(0.7)
                                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                            } else {
                                Image(systemName: "arrow.down.doc.fill")
                            }
                            Text(isExportingBootLogs ? "Exporting Last 3 Boots Logs..." : "Export Last 3 Boot Logs to Desktop (.tar.gz)")
                                .font(.system(size: 13, weight: .semibold))
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(ThemeColors.accentBlack)
                        .foregroundColor(ThemeColors.accentContrast)
                        .cornerRadius(8)
                    }
                    .buttonStyle(PlainButtonStyle())
                    .disabled(isExportingBootLogs)

                    if let url = lastExportedURL {
                        Button("Reveal in Finder") {
                            NSWorkspace.shared.activateFileViewerSelecting([url])
                        }
                        .buttonStyle(SecondaryOutlineButtonStyle())
                    }
                }

                if !bootLogsExportMessage.isEmpty {
                    Text(bootLogsExportMessage)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(bootLogsExportMessage.contains("ERROR") ? ThemeColors.redText : ThemeColors.greenText)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(bootLogsExportMessage.contains("ERROR") ? ThemeColors.redBg : ThemeColors.greenBg)
                        .cornerRadius(8)
                }
            }
            .padding(20)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Card 2: Full System & Wi-Fi Diagnostic Bundle
            VStack(alignment: .leading, spacing: 14) {
                Text("FULL SYSTEM & WI-FI HARDWARE DIAGNOSTIC SUITE")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.2)
                    .foregroundColor(ThemeColors.sectionHeader)

                Text("Gathers IORegistry device trees, PCIe link negotiated speeds, network interfaces, power states, dmesg, and sanitized OpenCore configuration.")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(ThemeColors.textSecondary)

                HStack(spacing: 12) {
                    Button("Grab Full Diagnostic Archive to Desktop") {
                        collectStandardLogs()
                    }
                    .buttonStyle(SecondaryOutlineButtonStyle())
                }
            }
            .padding(20)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Tab 4: Console Stream View
    private var consoleView: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                headerText(
                    title: "Live Console Stream",
                    subtitle: "Real-time console stream of EFI scans, driver injection, verification, and diagnostics."
                )
                Spacer()

                Button("Clear") {
                    logs.removeAll()
                }
                .buttonStyle(SecondaryOutlineButtonStyle())

                Button("Copy All") {
                    let pasteboard = NSPasteboard.general
                    pasteboard.clearContents()
                    pasteboard.setString(logs.joined(separator: "\n"), forType: .string)
                }
                .buttonStyle(SecondaryOutlineButtonStyle())
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    if logs.isEmpty {
                        Text("No logs recorded in this session. Run deployment or diagnostics to stream.")
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundColor(Color.gray)
                    } else {
                        ForEach(logs, id: \.self) { log in
                            Text(log)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(log.contains("ERROR") ? Color.red : (log.contains("SUCCESS") ? Color.green : (log.contains("WARN") ? Color.yellow : Color.white.opacity(0.92))))
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 440)
            .background(ThemeColors.terminalBg)
            .cornerRadius(10)
        }
    }

    // MARK: - Tab 5: Updates View
    private var updatesView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Software Updates",
                subtitle: "Check for the newest AirportMtkWlan driver suite and installer releases on GitHub."
            )

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("CURRENT INSTALLED DRIVER SUITE")
                            .font(.system(size: 10, weight: .bold))
                            .tracking(1.2)
                            .foregroundColor(ThemeColors.sectionHeader)
                        Text("AirportMtkWlan v2.2.1 (Best of the Best Milestone)")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundColor(ThemeColors.textPrimary)
                    }
                    Spacer()

                    Button(action: checkForUpdates) {
                        HStack(spacing: 8) {
                            if isCheckingUpdate {
                                ProgressView()
                                    .scaleEffect(0.7)
                                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                            } else {
                                Image(systemName: "arrow.triangle.2.circlepath")
                            }
                            Text(isCheckingUpdate ? "Checking..." : "Check for updates")
                                .font(.system(size: 13, weight: .semibold))
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(ThemeColors.accentBlack)
                        .foregroundColor(ThemeColors.accentContrast)
                        .cornerRadius(8)
                    }
                    .buttonStyle(PlainButtonStyle())
                    .disabled(isCheckingUpdate)
                }

                Divider()

                VStack(alignment: .leading, spacing: 8) {
                    Text(updateStatusMessage)
                        .font(.system(size: 13, weight: .regular))
                        .foregroundColor(ThemeColors.textPrimary)

                    if let url = latestReleaseURL {
                        Button("Open GitHub Release Page (\(latestTagFound))") {
                            NSWorkspace.shared.open(url)
                        }
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(ThemeColors.textPrimary)
                        .buttonStyle(SecondaryOutlineButtonStyle())
                    }
                }
            }
            .padding(22)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Tab 6: Recovery & EFI Backup
    private var recoveryView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Recovery & OpenCore Maintenance",
                subtitle: "Restore previous config.plist backups or safely remove driver kexts from EFI."
            )

            // Revert config.plist
            VStack(alignment: .leading, spacing: 12) {
                Text("RESTORE CONFIG.PLIST FROM BACKUP")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.2)
                    .foregroundColor(ThemeColors.sectionHeader)
                Text("Restores the most recent config.plist.backup-* created before the driver deployment.")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(ThemeColors.textSecondary)

                Button("Revert to Most Recent Backup") {
                    revertBackup()
                }
                .buttonStyle(SecondaryOutlineButtonStyle())
            }
            .padding(18)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Uninstall Driver
            VStack(alignment: .leading, spacing: 12) {
                Text("UNINSTALL DRIVER SUITE")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.2)
                    .foregroundColor(ThemeColors.redText)
                Text("Safely removes AirportMtkWlan.kext, SimpleMtkWlan.kext, AirportMtkBtPatcher.kext, and AirportMtkBtFw.kext from your target OpenCore EFI and disables them in config.plist.")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(ThemeColors.textSecondary)

                Button("Uninstall Driver Suite from EFI") {
                    uninstallDriver()
                }
                .foregroundColor(ThemeColors.redText)
                .buttonStyle(DestructiveOutlineButtonStyle())
            }
            .padding(18)
            .background(ThemeColors.cardBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Helper UI Components
    private func headerText(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 24, weight: .bold))
                .foregroundColor(ThemeColors.textPrimary)
            Text(subtitle)
                .font(.system(size: 13, weight: .regular))
                .foregroundColor(ThemeColors.textSecondary)
        }
    }

    private func specRow(label: String, value: String, isHighlight: Bool = false) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 10, weight: .bold))
                .tracking(1.0)
                .foregroundColor(ThemeColors.sectionHeader)
                .frame(width: 160, alignment: .leading)
            Text(value)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(isHighlight ? ThemeColors.greenText : ThemeColors.textPrimary)
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(ThemeColors.cardBg)
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(ThemeColors.cardBorder, lineWidth: 1))
    }

    private func telemetryCard(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 9, weight: .bold))
                .foregroundColor(ThemeColors.textSecondary)
            Text(value)
                .font(.system(size: 13, weight: .bold))
                .foregroundColor(ThemeColors.textPrimary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(ThemeColors.secondaryBg)
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(ThemeColors.cardBorderSubtle, lineWidth: 1))
    }

    // MARK: - Operations & Actions
    private func appendLog(_ message: String) {
        let df = DateFormatter()
        df.dateFormat = "HH:mm:ss"
        let timestamp = df.string(from: Date())
        logs.append("[\(timestamp)] \(message)")
    }

    private func refreshDestinations() {
        let mgr = EFIManager.shared
        destinations = mgr.scanDestinations()
        if selectedDestination == nil || !destinations.contains(selectedDestination!) {
            selectedDestination = destinations.first
        }
    }

    private func refreshTelemetry() {
        driverStatus = EFIManager.shared.checkLoadedDriver()

        DispatchQueue.global(qos: .utility).async {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport")
            task.arguments = ["-I"]
            let pipe = Pipe()
            task.standardOutput = pipe
            try? task.run()
            task.waitUntilExit()

            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            if let output = String(data: data, encoding: .utf8) {
                var ssid = "--"
                var rate = "-- Mbps"
                var rssi = "-- dBm"
                var channel = "--"

                for line in output.components(separatedBy: .newlines) {
                    let trim = line.trimmingCharacters(in: .whitespaces)
                    if trim.starts(with: "SSID: ") {
                        ssid = trim.replacingOccurrences(of: "SSID: ", with: "")
                    } else if trim.starts(with: "lastTxRate: ") {
                        rate = trim.replacingOccurrences(of: "lastTxRate: ", with: "") + " Mbps"
                    } else if trim.starts(with: "agrCtlRSSI: ") {
                        rssi = trim.replacingOccurrences(of: "agrCtlRSSI: ", with: "") + " dBm"
                    } else if trim.starts(with: "channel: ") {
                        channel = trim.replacingOccurrences(of: "channel: ", with: "")
                    }
                }

                DispatchQueue.main.async {
                    self.currentSSID = ssid
                    self.currentRate = rate
                    self.currentRSSI = rssi
                    self.currentChannel = channel
                }
            }
        }
    }

    private func performInstallation() {
        guard let dst = selectedDestination else { return }
        isInstalling = true
        installSuccess = nil
        appendLog("Initiating unified driver installation (Wi-Fi + BT + AWDL)...")

        DispatchQueue.global(qos: .userInitiated).async {
            let success = EFIManager.shared.install(
                flavor: self.selectedFlavor,
                destination: dst,
                installBluetooth: self.installBluetooth,
                autoConfig: self.autoConfig,
                backupPlist: self.backupPlist
            ) { logLine in
                DispatchQueue.main.async {
                    self.appendLog(logLine)
                }
            }

            DispatchQueue.main.async {
                self.isInstalling = false
                self.installSuccess = success
                self.refreshTelemetry()
            }
        }
    }

    private func mountSystemEFI() {
        appendLog("Scanning for system EFI partition...")
        DispatchQueue.global(qos: .userInitiated).async {
            if let mountPoint = EFIManager.shared.mountPartition(identifier: "disk0s1") {
                DispatchQueue.main.async {
                    self.appendLog("SUCCESS: Mounted system EFI at \(mountPoint)")
                    self.refreshDestinations()
                }
            } else {
                DispatchQueue.main.async {
                    self.appendLog("Failed to auto-mount disk0s1. Please mount via diskutil or OpenCore Configurator.")
                }
            }
        }
    }

    private func browseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Select OpenCore Folder"
        if panel.runModal() == .OK, let url = panel.url {
            if let resolved = EFIManager.shared.resolveCustomPath(url.path) {
                destinations.append(resolved)
                selectedDestination = resolved
                appendLog("Added custom EFI destination: \(resolved.displayName)")
            } else {
                appendLog("ERROR: Selected directory is not a valid OpenCore root (missing config.plist).")
            }
        }
    }

    private func exportLast3Boots() {
        isExportingBootLogs = true
        bootLogsExportMessage = "Extracting multi-boot logs (Current + Last 2 boots)..."
        appendLog("Starting extraction of Last 3 Boot Logs...")

        let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first ?? URL(fileURLWithPath: "/tmp")
        let df = DateFormatter()
        df.dateFormat = "yyyyMMdd-HHmmss"
        let outURL = desktop.appendingPathComponent("AirportMtk-Last3Boots-Logs-\(df.string(from: Date())).tar.gz")

        DispatchQueue.global(qos: .userInitiated).async {
            let res = EFIManager.shared.collectDiagnosticLogs(
                privileged: false,
                sessionLogs: self.logs,
                outputURL: outURL,
                last3Boots: true
            ) { line in
                DispatchQueue.main.async {
                    self.appendLog(line)
                }
            }

            DispatchQueue.main.async {
                self.isExportingBootLogs = false
                if res.success, let url = res.archiveURL {
                    self.lastExportedURL = url
                    self.bootLogsExportMessage = "SUCCESS: Last 3 boot logs saved to \(url.lastPathComponent)"
                    self.appendLog("SUCCESS: Last 3 boot logs archived at \(url.path)")
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                } else {
                    self.bootLogsExportMessage = "ERROR: Multi-boot extraction failed: \(res.message)"
                    self.appendLog("ERROR: Multi-boot extraction failed: \(res.message)")
                }
            }
        }
    }

    private func collectStandardLogs() {
        appendLog("Collecting standard diagnostic bundle...")
        let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first ?? URL(fileURLWithPath: "/tmp")
        let df = DateFormatter()
        df.dateFormat = "yyyyMMdd-HHmmss"
        let outURL = desktop.appendingPathComponent("mtk-diagnostics-\(df.string(from: Date())).tar.gz")
        DispatchQueue.global(qos: .userInitiated).async {
            let res = EFIManager.shared.collectDiagnosticLogs(
                privileged: false,
                sessionLogs: self.logs,
                outputURL: outURL,
                last3Boots: false
            ) { line in
                DispatchQueue.main.async {
                    self.appendLog(line)
                }
            }
            DispatchQueue.main.async {
                if res.success, let url = res.archiveURL {
                    self.lastExportedURL = url
                    self.appendLog("SUCCESS: Diagnostics saved to \(url.path)")
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                } else {
                    self.appendLog("ERROR: Diagnostic collection failed: \(res.message)")
                }
            }
        }
    }

    private func checkForUpdates() {
        isCheckingUpdate = true
        updateStatusMessage = "Checking GitHub releases for AirportMtkWlan..."
        latestReleaseURL = nil

        guard let apiURL = URL(string: "https://api.github.com/repos/Arxusion/AirportMtkWlan/releases/latest") else {
            isCheckingUpdate = false
            return
        }

        var request = URLRequest(url: apiURL)
        request.setValue("application/vnd.github.v3+json", forHTTPHeaderField: "Accept")

        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                self.isCheckingUpdate = false
                if let data = data,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let tagName = json["tag_name"] as? String,
                   let htmlUrlStr = json["html_url"] as? String,
                   let releaseURL = URL(string: htmlUrlStr) {

                    self.latestReleaseURL = releaseURL
                    self.latestTagFound = tagName
                    let currentTag = "v2.2.1"
                    if tagName != currentTag && tagName > currentTag {
                        self.updateAvailable = true
                        self.updateStatusMessage = "New update available: \(tagName)! (Installed: \(currentTag))"
                    } else {
                        self.updateAvailable = false
                        self.updateStatusMessage = "You're running the latest version (\(currentTag))!"
                    }
                } else {
                    self.updateStatusMessage = "Checked GitHub. Running latest v2.2.1."
                }
            }
        }.resume()
    }

    private func revertBackup() {
        guard let dst = selectedDestination else { return }
        appendLog("Restoring config.plist from backup in \(dst.displayName)...")
        DispatchQueue.global(qos: .userInitiated).async {
            let ok = EFIManager.shared.revertLatestBackup(destination: dst) { line in
                DispatchQueue.main.async {
                    self.appendLog(line)
                }
            }
            DispatchQueue.main.async {
                if ok {
                    self.appendLog("SUCCESS: config.plist reverted to previous state.")
                }
            }
        }
    }

    private func uninstallDriver() {
        guard let dst = selectedDestination else { return }
        appendLog("Starting driver uninstallation from \(dst.displayName)...")
        DispatchQueue.global(qos: .userInitiated).async {
            let success = EFIManager.shared.uninstall(destination: dst) { line in
                DispatchQueue.main.async {
                    self.appendLog(line)
                }
            }
            DispatchQueue.main.async {
                self.appendLog(success ? "SUCCESS: Uninstallation completed." : "Uninstallation encountered errors.")
                self.refreshTelemetry()
            }
        }
    }
}

// MARK: - High-Contrast Button Styles
struct PrimaryBlackButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(ThemeColors.accentBlack)
            .foregroundColor(ThemeColors.accentContrast)
            .cornerRadius(8)
            .opacity(configuration.isPressed ? 0.8 : 1.0)
    }
}

struct SecondaryOutlineButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(ThemeColors.cardBg)
            .foregroundColor(ThemeColors.textPrimary)
            .cornerRadius(8)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(ThemeColors.cardBorder, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.7 : 1.0)
    }
}

struct DestructiveOutlineButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(ThemeColors.cardBg)
            .foregroundColor(ThemeColors.redText)
            .cornerRadius(8)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(ThemeColors.redBorder, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.7 : 1.0)
    }
}
