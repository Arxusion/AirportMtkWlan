//
//  InstallerApp.swift
//  AirportMtkWlan Installer
//
//  Copyright © 2026 Aswini Soni (Arxusion). All rights reserved.
//

import SwiftUI
import AppKit

struct ContentView: View {
    @State private var destinations: [EFIDestination] = []
    @State private var selectedDestinationId: String = ""
    @State private var selectedFlavor: DriverFlavor = .tahoe
    @State private var autoConfig: Bool = true
    @State private var backupPlist: Bool = true
    @State private var logs: [String] = []
    @State private var isProcessing: Bool = false
    @State private var driverStatus: DriverStatus = DriverStatus(isLoaded: false, loadedVersion: nil, kextIdentifier: nil)
    @State private var alertTitle: String = ""
    @State private var alertMessage: String = ""
    @State private var showAlert: Bool = false
    
    var currentDestination: EFIDestination? {
        destinations.first { $0.id == selectedDestinationId }
    }
    
    var isCurrentValidOC: Bool {
        currentDestination?.isValidOC ?? false
    }
    
    var body: some View {
        VStack(spacing: 16) {
            // MARK: - Header
            HStack(spacing: 14) {
                ZStack {
                    LinearGradient(
                        colors: [Color.blue, Color.cyan],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    
                    Image(systemName: "wifi")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundColor(.white)
                }
                
                VStack(alignment: .leading, spacing: 2) {
                    Text("AirportMtkWlan")
                        .font(.system(size: 18, weight: .bold))
                    Text("MediaTek MT7921 / MT7922 OpenCore Installer")
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                }
                
                Spacer()
                
                // Driver status pill
                HStack(spacing: 6) {
                    Circle()
                        .fill(driverStatus.isLoaded ? Color.green : Color.gray)
                        .frame(width: 8, height: 8)
                    Text(driverStatus.isLoaded ? "Driver Active" : "Not Loaded")
                        .font(.system(size: 11, weight: .medium))
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Color(NSColor.controlBackgroundColor))
                .clipShape(Capsule())
            }
            .padding(.horizontal)
            .padding(.top, 12)
            
            Divider()
            
            // MARK: - Body Form
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    
                    // 1. Destination Card
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Target OpenCore EFI", systemImage: "externaldrive.fill")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(.primary)
                        
                        HStack(spacing: 10) {
                            Picker("", selection: $selectedDestinationId) {
                                if destinations.isEmpty {
                                    Text("Scanning for EFI...").tag("")
                                }
                                ForEach(destinations) { dest in
                                    Text(dest.displayName).tag(dest.id)
                                }
                            }
                            .labelsHidden()
                            .pickerStyle(MenuPickerStyle())
                            .frame(maxWidth: .infinity)
                            
                            Button(action: refreshDestinations) {
                                Image(systemName: "arrow.clockwise")
                            }
                            .help("Rescan Disks and Volumes")
                            
                            Button("Browse...") {
                                chooseCustomFolder()
                            }
                            .help("Select custom EFI folder")
                        }
                        
                        // Action row for unmounted partition
                        if let curr = currentDestination, !curr.isMounted, let diskId = curr.diskIdentifier {
                            HStack {
                                Text("This EFI partition is currently unmounted.")
                                    .font(.system(size: 11))
                                    .foregroundColor(.orange)
                                Spacer()
                                Button("Mount Partition") {
                                    mountDisk(diskId)
                                }
                                .font(.system(size: 11))
                            }
                            .padding(8)
                            .background(Color.orange.opacity(0.1))
                            .cornerRadius(6)
                        }
                        
                        // Validation status banner
                        if let curr = currentDestination, curr.isMounted {
                            HStack(spacing: 6) {
                                Image(systemName: curr.isValidOC ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                    .foregroundColor(curr.isValidOC ? .green : .yellow)
                                Text(curr.isValidOC ? "Valid OpenCore structure detected." : "config.plist not found in this folder.")
                                    .font(.system(size: 11))
                                    .foregroundColor(curr.isValidOC ? .secondary : .orange)
                            }
                        }
                    }
                    .padding(12)
                    .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
                    .cornerRadius(10)
                    
                    // 2. Flavor & Version Selection
                    VStack(alignment: .leading, spacing: 8) {
                        Label("macOS Target & Driver Flavor", systemImage: "gearshape.2.fill")
                            .font(.system(size: 13, weight: .semibold))
                        
                        Picker("", selection: $selectedFlavor) {
                            ForEach(DriverFlavor.allCases) { flavor in
                                Text(flavor.rawValue).tag(flavor)
                            }
                        }
                        .pickerStyle(RadioGroupPickerStyle())
                        
                        Text(flavorDescription(selectedFlavor))
                            .font(.system(size: 11))
                            .foregroundColor(.secondary)
                            .padding(.top, 2)
                    }
                    .padding(12)
                    .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
                    .cornerRadius(10)
                    
                    // 3. OpenCore Options
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Configuration Options", systemImage: "slider.horizontal.3")
                            .font(.system(size: 13, weight: .semibold))
                        
                        Toggle("Automatically configure config.plist (Kernel -> Add)", isOn: $autoConfig)
                            .font(.system(size: 12))
                        
                        Toggle("Create timestamped backup before modifying config.plist", isOn: $backupPlist)
                            .font(.system(size: 12))
                    }
                    .padding(12)
                    .background(Color(NSColor.controlBackgroundColor).opacity(0.6))
                    .cornerRadius(10)
                    
                    // 4. Primary Actions
                    HStack(spacing: 12) {
                        Button(action: installDriver) {
                            HStack {
                                if isProcessing {
                                    ProgressView()
                                        .controlSize(.small)
                                } else {
                                    Image(systemName: "arrow.down.circle.fill")
                                }
                                Text("Install to EFI")
                                    .fontWeight(.semibold)
                            }
                            .frame(maxWidth: .infinity)
                            .frame(height: 32)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(isProcessing || !isCurrentValidOC)
                        
                        Button(action: uninstallDriver) {
                            HStack {
                                Image(systemName: "trash")
                                Text("Uninstall")
                            }
                            .frame(height: 32)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isProcessing || !isCurrentValidOC)
                        
                        Button(action: exportDiagnostics) {
                            Image(systemName: "doc.text.magnifyingglass")
                            Text("Diagnostics")
                        }
                        .buttonStyle(.bordered)
                        .help("Export persistent kernel debug ring buffer (mtklog)")
                    }
                    
                    // 5. Activity Log Console
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Label("Installation Activity Log", systemImage: "terminal")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundColor(.secondary)
                            Spacer()
                            Button("Clear") {
                                logs.removeAll()
                            }
                            .buttonStyle(.plain)
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                        }
                        
                        ScrollViewReader { proxy in
                            ScrollView {
                                LazyVStack(alignment: .leading, spacing: 3) {
                                    if logs.isEmpty {
                                        Text("Ready. Select target OpenCore partition to begin.")
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundColor(.gray)
                                    }
                                    ForEach(0..<logs.count, id: \.self) { idx in
                                        Text(logs[idx])
                                            .font(.system(size: 10, design: .monospaced))
                                            .foregroundColor(.primary)
                                            .id(idx)
                                    }
                                }
                                .padding(8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(height: 110)
                            .background(Color(NSColor.textBackgroundColor))
                            .cornerRadius(6)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.gray.opacity(0.2)))
                            .onChange(of: logs.count) { _, _ in
                                if let last = logs.indices.last {
                                    proxy.scrollTo(last, anchor: .bottom)
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal)
            }
        }
        .frame(width: 540, height: 600)
        .onAppear {
            setupInitialState()
        }
        .alert(isPresented: $showAlert) {
            Alert(title: Text(alertTitle), message: Text(alertMessage), dismissButton: .default(Text("OK")))
        }
    }
    
    // MARK: - Actions
    
    private func setupInitialState() {
        refreshDestinations()
        refreshDriverStatus()
        
        // Auto-select macOS version
        let osVersion = ProcessInfo.processInfo.operatingSystemVersion
        if osVersion.majorVersion >= 26 {
            selectedFlavor = .tahoe
            appendLog("Host detected: macOS \(osVersion.majorVersion).\(osVersion.minorVersion) Tahoe (Build \(osVersion.patchVersion))")
        } else if osVersion.majorVersion == 15 {
            selectedFlavor = .sequoia
            appendLog("Host detected: macOS 15.\(osVersion.minorVersion) Sequoia")
        } else {
            selectedFlavor = .ethernet
            appendLog("Host detected: macOS \(osVersion.majorVersion).\(osVersion.minorVersion) (Virtual Ethernet mode recommended)")
        }
    }
    
    private func refreshDestinations() {
        appendLog("Scanning available disks and OpenCore partitions...")
        let found = EFIManager.shared.scanDestinations()
        destinations = found
        if let firstValid = found.first(where: { $0.isValidOC }) {
            selectedDestinationId = firstValid.id
            appendLog("Selected OpenCore at: \(firstValid.ocPath)")
        } else if let first = found.first {
            selectedDestinationId = first.id
        }
    }
    
    private func refreshDriverStatus() {
        driverStatus = EFIManager.shared.checkLoadedDriver()
    }
    
    private func chooseCustomFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.message = "Select OpenCore or EFI folder"
        panel.prompt = "Select"
        
        if panel.runModal() == .OK, let url = panel.url {
            if let dest = EFIManager.shared.resolveCustomPath(url.path) {
                if !destinations.contains(where: { $0.id == dest.id }) {
                    destinations.append(dest)
                }
                selectedDestinationId = dest.id
                appendLog("Custom destination selected: \(dest.ocPath)")
            } else {
                appendLog("WARNING: Selected folder does not contain a valid OpenCore structure (config.plist / Kexts).")
                let unverified = EFIDestination(
                    id: url.path,
                    displayName: "Folder: \(url.lastPathComponent)",
                    ocPath: url.path,
                    isMounted: true,
                    diskIdentifier: nil,
                    isValidOC: false
                )
                destinations.append(unverified)
                selectedDestinationId = unverified.id
            }
        }
    }
    
    private func mountDisk(_ diskId: String) {
        appendLog("Attempting to mount \(diskId)...")
        if let mountPoint = EFIManager.shared.mountPartition(identifier: diskId) {
            appendLog("Successfully mounted at \(mountPoint)")
            refreshDestinations()
            selectedDestinationId = mountPoint
        } else {
            appendLog("Failed to mount \(diskId). Please mount using Disk Utility or Terminal.")
        }
    }
    
    private func installDriver() {
        guard let dest = currentDestination else { return }
        isProcessing = true
        
        DispatchQueue.global(qos: .userInitiated).async {
            let ok = EFIManager.shared.install(
                flavor: selectedFlavor,
                destination: dest,
                autoConfig: autoConfig,
                backupPlist: backupPlist
            ) { msg in
                DispatchQueue.main.async {
                    appendLog(msg)
                }
            }
            
            DispatchQueue.main.async {
                isProcessing = false
                if ok {
                    alertTitle = "Installation Successful"
                    alertMessage = "AirportMtkWlan has been installed to \(dest.ocPath). Restart your computer to load the updated driver."
                    showAlert = true
                } else {
                    alertTitle = "Installation Failed"
                    alertMessage = "Check the activity log below for detailed error information."
                    showAlert = true
                }
                refreshDriverStatus()
            }
        }
    }
    
    private func uninstallDriver() {
        guard let dest = currentDestination else { return }
        isProcessing = true
        
        DispatchQueue.global(qos: .userInitiated).async {
            let ok = EFIManager.shared.uninstall(destination: dest) { msg in
                DispatchQueue.main.async {
                    appendLog(msg)
                }
            }
            
            DispatchQueue.main.async {
                isProcessing = false
                if ok {
                    alertTitle = "Uninstalled"
                    alertMessage = "Wi-Fi driver kexts have been removed and disabled in config.plist."
                    showAlert = true
                }
                refreshDriverStatus()
            }
        }
    }
    
    private func exportDiagnostics() {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/ioreg")
        task.arguments = ["-l", "-w0"]
        let pipe = Pipe()
        task.standardOutput = pipe
        try? task.run()
        task.waitUntilExit()
        
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        var report = "=== AirportMtkWlan Diagnostic Dump ===\nDate: \(Date())\n\n"
        
        for line in out.components(separatedBy: "\n") {
            if line.contains("MtkDebugLog") || line.contains("IO80211") || line.contains("AirportMtkWlan") {
                report += line + "\n"
            }
        }
        
        let savePanel = NSSavePanel()
        savePanel.nameFieldStringValue = "mtk_diagnostic_\(Int(Date().timeIntervalSince1970)).txt"
        savePanel.prompt = "Save"
        if savePanel.runModal() == .OK, let url = savePanel.url {
            try? report.write(to: url, atomically: true, encoding: .utf8)
            appendLog("Diagnostic report saved to: \(url.lastPathComponent)")
        }
    }
    
    private func appendLog(_ text: String) {
        let df = DateFormatter()
        df.dateFormat = "HH:mm:ss"
        let timestamp = df.string(from: Date())
        logs.append("[\(timestamp)] \(text)")
    }
    
    private func flavorDescription(_ flavor: DriverFlavor) -> String {
        switch flavor {
        case .tahoe:
            return "Native Skywalk / IO80211 driver compiled for macOS 26 Tahoe (Kernel 25.x). Native Wi-Fi menu."
        case .sequoia:
            return "Native Skywalk / IO80211 driver compiled for macOS 15.2+ Sequoia (Kernel 24.x). Native Wi-Fi menu."
        case .ethernet:
            return "Ethernet driver compatible with older macOS releases via the SimpleMTKClient menu app."
        }
    }
}
