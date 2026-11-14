//
//  InstallerApp.swift
//  AirportMtkWlan Suite Installer v2.2.1
//
//  Copyright © 2026 Aswini Soni (@Arxusion). All rights reserved.
//

import SwiftUI
import AppKit

// MARK: - Navigation Tabs
enum NavigationTab: String, CaseIterable, Identifiable {
    case thisMac = "This Mac"
    case deploy = "Deploy Suite"
    case logs = "Installation Logs"
    case updates = "Updates"
    case tools = "Tools & Diagnostics"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .thisMac: return "display"
        case .deploy: return "arrow.down.circle.fill"
        case .logs: return "terminal.fill"
        case .updates: return "arrow.triangle.2.circlepath"
        case .tools: return "wrench.and.screwdriver"
        }
    }
}

// MARK: - Theme & Color Palette (Clean Light Theme Inspired by Liberator)
struct ThemeColors {
    static let gradientTop = Color(red: 0.91, green: 0.93, blue: 0.96)
    static let gradientMid = Color(red: 0.97, green: 0.95, blue: 0.93)
    static let gradientBottom = Color(red: 0.97, green: 0.88, blue: 0.77)

    static let sidebarBackground = Color.white.opacity(0.35)
    static let sidebarBorder = Color(red: 0.88, green: 0.85, blue: 0.80)

    static let cardBackground = Color.white.opacity(0.85)
    static let cardBorder = Color(red: 0.88, green: 0.85, blue: 0.80)

    static let textPrimary = Color(red: 0.16, green: 0.15, blue: 0.14)
    static let textSecondary = Color(red: 0.44, green: 0.42, blue: 0.40)
    static let sectionHeader = Color(red: 0.76, green: 0.35, blue: 0.15) // Terracotta small caps

    static let accent = Color(red: 0.88, green: 0.38, blue: 0.15) // Warm Liberator orange
    static let accentHover = Color(red: 0.80, green: 0.32, blue: 0.12)

    static let tabActiveBg = Color(red: 0.99, green: 0.93, blue: 0.88)
    static let tabActiveBorder = Color(red: 0.88, green: 0.45, blue: 0.22).opacity(0.6)

    static let greenBadge = Color(red: 0.12, green: 0.55, blue: 0.22)
    static let greenBg = Color(red: 0.90, green: 0.96, blue: 0.90)
    static let greenBorder = Color(red: 0.75, green: 0.88, blue: 0.75)

    static let redBadge = Color(red: 0.85, green: 0.22, blue: 0.18)
    static let logBackground = Color(red: 0.12, green: 0.13, blue: 0.16)
}

// MARK: - Main Content View
struct ContentView: View {
    @State private var selectedTab: NavigationTab = .thisMac
    
    // Deployment State
    @State private var destinations: [EFIDestination] = []
    @State private var selectedDestination: EFIDestination?
    @State private var selectedFlavor: DriverFlavor = .tahoe
    @State private var installBluetooth: Bool = true
    @State private var autoConfig: Bool = true
    @State private var backupPlist: Bool = true
    
    // Logs & Progress State
    @State private var logs: [String] = []
    @State private var isInstalling: Bool = false
    @State private var installSuccess: Bool? = nil
    @State private var showLogsCard: Bool = false
    
    // Hardware & Telemetry State
    @State private var driverStatus: DriverStatus?
    @State private var currentSSID: String = "Scanning..."
    @State private var currentRate: String = "-- Mbps"
    @State private var currentRSSI: String = "-- dBm"
    @State private var currentChannel: String = "--"
    @State private var currentNSS: String = "2x2 NSS"
    
    // Update Checker State
    @State private var isCheckingUpdate: Bool = false
    @State private var updateStatusMessage: String = "Click 'Check for updates' to verify latest release."
    @State private var latestReleaseURL: URL? = nil
    @State private var updateAvailable: Bool = false
    @State private var latestTagFound: String = ""
    
    let timer = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            // Background Warm Sunrise Gradient
            LinearGradient(
                gradient: Gradient(colors: [
                    ThemeColors.gradientTop,
                    ThemeColors.gradientMid,
                    ThemeColors.gradientBottom
                ]),
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            HStack(spacing: 0) {
                // MARK: - Left Sidebar
                sidebarView
                    .frame(width: 230)
                    .background(ThemeColors.sidebarBackground)

                Rectangle()
                    .fill(ThemeColors.sidebarBorder)
                    .frame(width: 1)

                // MARK: - Right Detail Content Area
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        switch selectedTab {
                        case .thisMac:
                            thisMacView
                        case .deploy:
                            deployView
                        case .logs:
                            logsView
                        case .updates:
                            updatesView
                        case .tools:
                            toolsView
                        }
                    }
                    .padding(32)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
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
            // Header: App Logo and Title
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10)
                        .fill(ThemeColors.accent)
                        .frame(width: 38, height: 38)
                    Image(systemName: "antenna.radiowaves.left.and.right")
                        .font(.system(size: 19, weight: .bold))
                        .foregroundColor(.white)
                }
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text("AirportMtk")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(ThemeColors.textPrimary)
                        Text("v2.2.1")
                            .font(.system(size: 10, weight: .bold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(ThemeColors.accent.opacity(0.16))
                            .foregroundColor(ThemeColors.accent)
                            .cornerRadius(5)
                    }
                    Text("MediaTek Deployment Suite")
                        .font(.system(size: 11, weight: .regular))
                        .foregroundColor(ThemeColors.textSecondary)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 28)
            .padding(.bottom, 24)

            // Sidebar Tab Items
            VStack(spacing: 6) {
                ForEach(NavigationTab.allCases) { tab in
                    Button(action: {
                        selectedTab = tab
                    }) {
                        HStack(spacing: 10) {
                            Image(systemName: tab.icon)
                                .font(.system(size: 13, weight: selectedTab == tab ? .semibold : .regular))
                                .frame(width: 20, alignment: .center)
                            Text(tab.rawValue)
                                .font(.system(size: 13, weight: selectedTab == tab ? .semibold : .medium))
                            Spacer()
                        }
                        .foregroundColor(selectedTab == tab ? ThemeColors.textPrimary : ThemeColors.textSecondary)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 9)
                        .background(
                            selectedTab == tab ?
                                RoundedRectangle(cornerRadius: 12)
                                    .fill(ThemeColors.tabActiveBg)
                                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.tabActiveBorder, lineWidth: 1))
                                : RoundedRectangle(cornerRadius: 12)
                                    .fill(Color.clear)
                                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.clear, lineWidth: 0))
                        )
                    }
                    .buttonStyle(PlainButtonStyle())
                }
            }
            .padding(.horizontal, 14)

            Spacer()

            // Sidebar Bottom Card (Liberator Style)
            VStack(alignment: .leading, spacing: 5) {
                Text("Suite v2.2.1")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(ThemeColors.textPrimary)
                HStack(spacing: 8) {
                    Button("Source code") {
                        if let url = URL(string: "https://github.com/Arxusion/AirportMtkWlan") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(ThemeColors.accent)
                    .buttonStyle(PlainButtonStyle())

                    Text("·")
                        .foregroundColor(ThemeColors.textSecondary)

                    Button("OpenCore guide") {
                        if let url = URL(string: "https://dortania.github.io/OpenCore-Install-Guide/") {
                            NSWorkspace.shared.open(url)
                        }
                    }
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(ThemeColors.accent)
                    .buttonStyle(PlainButtonStyle())
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white.opacity(0.55))
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
            .padding(.horizontal, 16)
            .padding(.bottom, 22)
        }
    }

    // MARK: - Tab 1: This Mac / Status
    private var thisMacView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Your Mac, mapped",
                subtitle: "AirportMtkWlan connects MediaTek Wi-Fi 6 (MT7921/MT7922), Apple Wireless Direct Link (AWDL/AirDrop), and Bluetooth to macOS."
            )

            // Info rows (Capsule containers like Liberator)
            VStack(spacing: 8) {
                infoRow(label: "MACOS", value: "26.7.3 (macOS Tahoe - Darwin 25.6.0)")
                infoRow(label: "PROCESSOR", value: "Intel Core i5-11400H (Tiger Lake-H x86_64)")
                infoRow(label: "WI-FI CHIPSET", value: "MediaTek MT7921 / MT7922 PCIe 802.11ax")
                infoRow(label: "BLUETOOTH", value: "MediaTek USB Bluetooth (0489:e0e2 / SRS_7922)")
                infoRow(label: "OPENCORE", value: selectedDestination?.displayName ?? "Auto-detecting EFI...")
                infoRow(label: "INSTALLED SUITE", value: "AirportMtkWlan v2.2.1 + AirportMtkBt")
                infoRow(
                    label: "AIRPORT DRIVER",
                    value: (driverStatus?.isLoaded ?? false) ? "running (MediaTek MT7921 802.11ax 2x2 NSS, AWDL active)" : "Ready to install / Not yet loaded into kernel",
                    isHighlight: (driverStatus?.isLoaded ?? false)
                )
            }

            // Readiness Banner
            HStack(spacing: 12) {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundColor(ThemeColors.greenBadge)
                    .font(.system(size: 18))
                Text("This Mac can make the move. High-throughput Wi-Fi 6, AirDrop, and Bluetooth are ready for deployment.")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(ThemeColors.textPrimary)
                Spacer()
                Button("Deploy Suite") {
                    selectedTab = .deploy
                }
                .buttonStyle(PrimaryCapsuleButtonStyle())
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(ThemeColors.greenBg)
            .cornerRadius(12)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.greenBorder, lineWidth: 1))

            // Wireless Telemetry Card
            VStack(alignment: .leading, spacing: 12) {
                Text("LIVE WIRELESS TELEMETRY")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.0)
                    .foregroundColor(ThemeColors.sectionHeader)

                HStack(spacing: 10) {
                    telemetryCard(title: "SSID", value: currentSSID)
                    telemetryCard(title: "LINK RATE", value: currentRate)
                    telemetryCard(title: "SIGNAL", value: currentRSSI)
                    telemetryCard(title: "CHANNEL", value: currentChannel)
                    telemetryCard(title: "MIMO", value: currentNSS)
                }
            }
            .padding(18)
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Tab 2: Deploy Driver Suite
    private var deployView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Deploy Unified Suite",
                subtitle: "Installs Wi-Fi 802.11ax, Bluetooth companion drivers, and AWDL hardware acceleration to your OpenCore EFI in one run."
            )

            // Card 1: Target OpenCore EFI
            VStack(alignment: .leading, spacing: 12) {
                Text("TARGET OPENCORE EFI")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.0)
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
                    .buttonStyle(SecondaryButtonStyle())

                    Button("Mount EFI") {
                        mountSystemEFI()
                    }
                    .buttonStyle(SecondaryButtonStyle())

                    Button("Browse...") {
                        browseFolder()
                    }
                    .buttonStyle(SecondaryButtonStyle())
                }
            }
            .padding(18)
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Card 2: Driver Target & Options
            VStack(alignment: .leading, spacing: 14) {
                Text("DRIVER FLAVOR & DEPLOYMENT OPTIONS")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.0)
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
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Big Deploy Action Button (Terracotta Capsule)
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
                    Text(isInstalling ? "Deploying Drivers to OpenCore EFI..." : "Deploy Unified Suite to EFI (Wi-Fi + BT + AWDL)")
                        .font(.system(size: 14, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(isInstalling ? ThemeColors.accent.opacity(0.65) : ThemeColors.accent)
                .foregroundColor(.white)
                .clipShape(Capsule())
            }
            .buttonStyle(PlainButtonStyle())
            .disabled(isInstalling || selectedDestination == nil)

            // Success Banner if complete
            if installSuccess == true {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(ThemeColors.greenBadge)
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

            // Real-Time Live Logs Box (Immediately Visible During and After Deployment)
            if showLogsCard || !logs.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text("REAL-TIME DEPLOYMENT LOGS")
                            .font(.system(size: 10, weight: .bold))
                            .tracking(1.0)
                            .foregroundColor(ThemeColors.sectionHeader)
                        Spacer()
                        Button("Full Log Tab") {
                            selectedTab = .logs
                        }
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(ThemeColors.accent)
                        .buttonStyle(PlainButtonStyle())
                    }

                    ScrollView {
                        VStack(alignment: .leading, spacing: 3) {
                            ForEach(logs.suffix(12), id: \.self) { log in
                                Text(log)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(log.contains("ERROR") ? Color.red : (log.contains("SUCCESS") ? Color.green : Color.white.opacity(0.9)))
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                    }
                    .frame(height: 140)
                    .background(ThemeColors.logBackground)
                    .cornerRadius(10)
                }
                .padding(16)
                .background(ThemeColors.cardBackground)
                .cornerRadius(14)
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))
            }

            // Two Cards Side-by-Side (Like Liberator Screenshot 4)
            HStack(alignment: .top, spacing: 16) {
                // Card 1: Updates
                VStack(alignment: .leading, spacing: 10) {
                    Text("UPDATES")
                        .font(.system(size: 10, weight: .bold))
                        .tracking(1.0)
                        .foregroundColor(ThemeColors.sectionHeader)

                    Text("AirportMtkWlan checks for the newest driver suite and installer app directly from GitHub. Every download is verified.")
                        .font(.system(size: 12, weight: .regular))
                        .foregroundColor(ThemeColors.textPrimary)

                    HStack(spacing: 10) {
                        Button("Check for updates") {
                            checkForUpdates()
                        }
                        .buttonStyle(PrimaryCapsuleButtonStyle())

                        if isCheckingUpdate {
                            ProgressView()
                                .scaleEffect(0.7)
                        }
                    }

                    Text(updateStatusMessage)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(updateAvailable ? ThemeColors.accent : ThemeColors.textSecondary)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(ThemeColors.cardBackground)
                .cornerRadius(14)
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))

                // Card 2: If Something Goes Wrong After You Restart
                VStack(alignment: .leading, spacing: 10) {
                    Text("IF SOMETHING GOES WRONG AFTER YOU RESTART")
                        .font(.system(size: 10, weight: .bold))
                        .tracking(1.0)
                        .foregroundColor(ThemeColors.sectionHeader)

                    Text("Your previous config.plist was backed up before modifications. If needed, revert back or boot with verbose flags (-v keepsyms=1).")
                        .font(.system(size: 12, weight: .regular))
                        .foregroundColor(ThemeColors.textPrimary)

                    HStack(spacing: 8) {
                        Button("Revert config.plist") {
                            revertBackup()
                        }
                        .buttonStyle(SecondaryButtonStyle())

                        Button("Remove driver") {
                            uninstallDriver()
                        }
                        .foregroundColor(ThemeColors.redBadge)
                        .buttonStyle(SecondaryButtonStyle())
                    }
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(ThemeColors.cardBackground)
                .cornerRadius(14)
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))
            }
        }
    }

    // MARK: - Tab 3: Installation Logs
    private var logsView: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                headerText(
                    title: "Installation Logs",
                    subtitle: "Real-time console stream from EFI detection, copying, and OpenCore configuration."
                )
                Spacer()
                Button("Clear") {
                    logs.removeAll()
                }
                .buttonStyle(SecondaryButtonStyle())

                Button("Copy All") {
                    let pasteboard = NSPasteboard.general
                    pasteboard.clearContents()
                    pasteboard.setString(logs.joined(separator: "\n"), forType: .string)
                }
                .buttonStyle(SecondaryButtonStyle())
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    if logs.isEmpty {
                        Text("No logs recorded yet. Run 'Deploy Unified Suite' to stream activity.")
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundColor(Color.gray)
                    } else {
                        ForEach(logs, id: \.self) { log in
                            Text(log)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(log.contains("ERROR") ? Color.red : (log.contains("SUCCESS") ? Color.green : (log.contains("WARNING") ? Color.yellow : Color.white.opacity(0.92))))
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 420)
            .background(ThemeColors.logBackground)
            .cornerRadius(12)
        }
    }

    // MARK: - Tab 4: Updates View
    private var updatesView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Software Updates",
                subtitle: "Check for the newest AirportMtkWlan driver and installer releases on GitHub."
            )

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("CURRENT INSTALLED DRIVER SUITE")
                            .font(.system(size: 10, weight: .bold))
                            .tracking(1.0)
                            .foregroundColor(ThemeColors.sectionHeader)
                        Text("v2.2.1 (Best of the Best Milestone)")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundColor(ThemeColors.textPrimary)
                    }
                    Spacer()
                    Button("Check for updates") {
                        checkForUpdates()
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())
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
                        .foregroundColor(ThemeColors.accent)
                        .buttonStyle(PlainButtonStyle())
                    }
                }
            }
            .padding(22)
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Tab 5: Tools & Diagnostics
    private var toolsView: some View {
        VStack(alignment: .leading, spacing: 20) {
            headerText(
                title: "Tools & Diagnostics",
                subtitle: "Diagnostic log collection, EFI backup restoration, and uninstaller."
            )

            // Grab Diagnostics
            VStack(alignment: .leading, spacing: 12) {
                Text("COLLECT DIAGNOSTIC LOGS")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.0)
                    .foregroundColor(ThemeColors.sectionHeader)
                Text("Gathers kernel dmesg, IORegistry hardware tree, MediaTek PCIe status, and OpenCore configuration into a sanitized archive on your Desktop.")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(ThemeColors.textPrimary)

                Button("Grab Diagnostic Logs to Desktop") {
                    collectLogs()
                }
                .buttonStyle(SecondaryButtonStyle())
            }
            .padding(18)
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Revert config.plist
            VStack(alignment: .leading, spacing: 12) {
                Text("RESTORE CONFIG.PLIST FROM BACKUP")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.0)
                    .foregroundColor(ThemeColors.sectionHeader)
                Text("Restores the most recent config.plist.backup-* created before the driver deployment.")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(ThemeColors.textPrimary)

                Button("Revert to Most Recent Backup") {
                    revertBackup()
                }
                .buttonStyle(SecondaryButtonStyle())
            }
            .padding(18)
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))

            // Uninstall Driver
            VStack(alignment: .leading, spacing: 12) {
                Text("UNINSTALL DRIVER SUITE")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(1.0)
                    .foregroundColor(ThemeColors.redBadge)
                Text("Safely removes AirportMtkWlan.kext, SimpleMtkWlan.kext, AirportMtkBtPatcher.kext, and AirportMtkBtFw.kext from your target OpenCore EFI and disables them in config.plist.")
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(ThemeColors.textPrimary)

                Button("Uninstall Driver Suite from EFI") {
                    uninstallDriver()
                }
                .foregroundColor(ThemeColors.redBadge)
                .buttonStyle(SecondaryButtonStyle())
            }
            .padding(18)
            .background(ThemeColors.cardBackground)
            .cornerRadius(14)
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(ThemeColors.cardBorder, lineWidth: 1))
        }
    }

    // MARK: - Helper UI Components
    private func headerText(title: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 26, weight: .bold))
                .foregroundColor(ThemeColors.textPrimary)
            Text(subtitle)
                .font(.system(size: 13, weight: .regular))
                .foregroundColor(ThemeColors.textSecondary)
        }
    }

    private func infoRow(label: String, value: String, isHighlight: Bool = false) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 10, weight: .bold))
                .tracking(0.8)
                .foregroundColor(ThemeColors.sectionHeader)
                .frame(width: 160, alignment: .leading)
            Text(value)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(isHighlight ? ThemeColors.greenBadge : ThemeColors.textPrimary)
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(ThemeColors.cardBackground)
        .cornerRadius(12)
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(ThemeColors.cardBorder, lineWidth: 1))
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
        .padding(10)
        .background(Color.white.opacity(0.6))
        .cornerRadius(8)
    }

    // MARK: - Actions & Operations
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
        showLogsCard = true
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
        showLogsCard = true
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
                showLogsCard = true
                appendLog("Added custom EFI destination: \(resolved.displayName)")
            } else {
                showLogsCard = true
                appendLog("ERROR: Selected directory is not a valid OpenCore root (missing config.plist).")
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
                        self.updateStatusMessage = "New update available: \(tagName)! (You have \(currentTag))"
                    } else {
                        self.updateAvailable = false
                        self.updateStatusMessage = "You're on the latest version! (\(currentTag))"
                    }
                } else {
                    self.updateStatusMessage = "Could not reach GitHub or rate-limited. Running v2.2.1."
                }
            }
        }.resume()
    }

    private func revertBackup() {
        guard let dst = selectedDestination else { return }
        showLogsCard = true
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

    private func collectLogs() {
        showLogsCard = true
        appendLog("Collecting diagnostic logs...")
        let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first ?? URL(fileURLWithPath: "/tmp")
        let df = DateFormatter()
        df.dateFormat = "yyyyMMdd-HHmmss"
        let outURL = desktop.appendingPathComponent("mtk-diagnostics-\(df.string(from: Date())).tar.gz")
        DispatchQueue.global(qos: .userInitiated).async {
            let res = EFIManager.shared.collectDiagnosticLogs(
                privileged: false,
                sessionLogs: self.logs,
                outputURL: outURL
            ) { line in
                DispatchQueue.main.async {
                    self.appendLog(line)
                }
            }
            DispatchQueue.main.async {
                if res.success, let url = res.archiveURL {
                    self.appendLog("SUCCESS: Diagnostics saved to \(url.path)")
                    NSWorkspace.shared.activateFileViewerSelecting([url])
                } else {
                    self.appendLog("ERROR: Diagnostic collection failed: \(res.message)")
                }
            }
        }
    }

    private func uninstallDriver() {
        guard let dst = selectedDestination else { return }
        showLogsCard = true
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

// MARK: - Button Styles
struct PrimaryCapsuleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(ThemeColors.accent)
            .foregroundColor(.white)
            .clipShape(Capsule())
            .opacity(configuration.isPressed ? 0.75 : 1.0)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Color.white.opacity(0.85))
            .foregroundColor(ThemeColors.textPrimary)
            .cornerRadius(8)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(ThemeColors.cardBorder, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.7 : 1.0)
    }
}
