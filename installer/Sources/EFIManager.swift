//
//  EFIManager.swift
//  AirportMtkWlan Installer
//
//  Copyright © 2026 Aswini Soni (Arxusion). All rights reserved.
//

import Foundation

public enum DriverFlavor: String, CaseIterable, Identifiable {
    case tahoe = "macOS 26 Tahoe (Native AirPort)"
    case sequoia = "macOS 15 Sequoia (Native AirPort)"
    case ethernet = "SimpleMtkWlan (Virtual Ethernet)"
    
    public var id: String { rawValue }
    
    public var kextName: String {
        switch self {
        case .tahoe, .sequoia:
            return "AirportMtkWlan.kext"
        case .ethernet:
            return "SimpleMtkWlan.kext"
        }
    }
    
    public var minKernel: String {
        switch self {
        case .tahoe: return "25.0.0"
        case .sequoia: return "24.2.0"
        case .ethernet: return ""
        }
    }
    
    public var maxKernel: String {
        switch self {
        case .tahoe: return "25.99.99"
        case .sequoia: return "24.99.99"
        case .ethernet: return ""
        }
    }
    
    public var resourceSubpath: String {
        switch self {
        case .tahoe: return "kexts/tahoe/AirportMtkWlan.kext"
        case .sequoia: return "kexts/sequoia/AirportMtkWlan.kext"
        case .ethernet: return "kexts/SimpleMtkWlan.kext"
        }
    }
}

public struct EFIDestination: Identifiable, Hashable {
    public let id: String
    public let displayName: String
    public let ocPath: String
    public let isMounted: Bool
    public let diskIdentifier: String?
    public let isValidOC: Bool
    
    public func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
    
    public static func == (lhs: EFIDestination, rhs: EFIDestination) -> Bool {
        lhs.id == rhs.id
    }
}

public struct DriverStatus {
    public let isLoaded: Bool
    public let loadedVersion: String?
    public let kextIdentifier: String?
}

public struct DiagnosticGrabResult {
    public let success: Bool
    public let archiveURL: URL?
    public let summaryText: String
    public let message: String
}

public class EFIManager {
    public static let shared = EFIManager()
    
    private init() {}
    
    // MARK: - Scan for OpenCore & EFI Partitions
    
    public func scanDestinations() -> [EFIDestination] {
        var destinations: [EFIDestination] = []
        let fm = FileManager.default
        
        // 1. Scan mounted volumes in /Volumes
        let volumesURL = URL(fileURLWithPath: "/Volumes")
        if let urls = try? fm.contentsOfDirectory(at: volumesURL, includingPropertiesForKeys: nil) {
            for vol in urls {
                let candidates = [
                    vol.appendingPathComponent("EFI/OC"),
                    vol.appendingPathComponent("OC"),
                    vol
                ]
                for cand in candidates {
                    let plist = cand.appendingPathComponent("config.plist")
                    let kexts = cand.appendingPathComponent("Kexts")
                    if fm.fileExists(atPath: plist.path) && fm.fileExists(atPath: kexts.path) {
                        let name = "\(vol.lastPathComponent) (\(cand.path.replacingOccurrences(of: vol.path, with: "")))"
                        destinations.append(EFIDestination(
                            id: cand.path,
                            displayName: name.replacingOccurrences(of: " ()", with: ""),
                            ocPath: cand.path,
                            isMounted: true,
                            diskIdentifier: nil,
                            isValidOC: true
                        ))
                        break
                    }
                }
            }
        }
        
        // 2. Scan physical EFI partitions using diskutil
        let rawDisks = getEFIPartitionsFromDiskutil()
        for disk in rawDisks {
            if let mount = disk.mountPoint, !mount.isEmpty {
                // If it was already added from /Volumes scan, skip duplicate
                let candOC = URL(fileURLWithPath: mount).appendingPathComponent("EFI/OC")
                if !destinations.contains(where: { $0.ocPath == candOC.path || $0.id == mount }) {
                    let plist = candOC.appendingPathComponent("config.plist")
                    let valid = fm.fileExists(atPath: plist.path)
                    destinations.append(EFIDestination(
                        id: mount,
                        displayName: "\(disk.name) [\(disk.id)] - \(disk.size)",
                        ocPath: valid ? candOC.path : mount,
                        isMounted: true,
                        diskIdentifier: disk.id,
                        isValidOC: valid
                    ))
                }
            } else {
                // Unmounted EFI partition
                destinations.append(EFIDestination(
                    id: disk.id,
                    displayName: "\(disk.name) [\(disk.id)] - \(disk.size) (Unmounted)",
                    ocPath: "",
                    isMounted: false,
                    diskIdentifier: disk.id,
                    isValidOC: false
                ))
            }
        }
        
        return destinations
    }
    
    public func resolveCustomPath(_ folderPath: String) -> EFIDestination? {
        let fm = FileManager.default
        let url = URL(fileURLWithPath: folderPath)
        let candidates = [
            url.appendingPathComponent("EFI/OC"),
            url.appendingPathComponent("OC"),
            url
        ]
        for cand in candidates {
            let plist = cand.appendingPathComponent("config.plist")
            let kexts = cand.appendingPathComponent("Kexts")
            if fm.fileExists(atPath: plist.path) && fm.fileExists(atPath: kexts.path) {
                return EFIDestination(
                    id: cand.path,
                    displayName: "Custom: \(url.lastPathComponent)",
                    ocPath: cand.path,
                    isMounted: true,
                    diskIdentifier: nil,
                    isValidOC: true
                )
            }
        }
        return nil
    }
    
    // MARK: - Mount Partition
    
    public func mountPartition(identifier: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/diskutil")
        process.arguments = ["mount", identifier]
        let pipe = Pipe()
        process.standardOutput = pipe
        try? process.run()
        process.waitUntilExit()
        
        if process.terminationStatus == 0 {
            // Find mount point
            let infoProcess = Process()
            infoProcess.executableURL = URL(fileURLWithPath: "/usr/sbin/diskutil")
            infoProcess.arguments = ["info", "-plist", identifier]
            let infoPipe = Pipe()
            infoProcess.standardOutput = infoPipe
            try? infoProcess.run()
            infoProcess.waitUntilExit()
            
            let data = infoPipe.fileHandleForReading.readDataToEndOfFile()
            if let plist = try? PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any],
               let mountPoint = plist["MountPoint"] as? String {
                return mountPoint
            }
        }
        return nil
    }
    
    // MARK: - Install Driver
    
    public func install(
        flavor: DriverFlavor,
        destination: EFIDestination,
        autoConfig: Bool,
        backupPlist: Bool,
        logger: @escaping (String) -> Void
    ) -> Bool {
        let fm = FileManager.default
        let ocURL = URL(fileURLWithPath: destination.ocPath)
        let kextsURL = ocURL.appendingPathComponent("Kexts")
        let plistURL = ocURL.appendingPathComponent("config.plist")
        
        logger("Starting installation for \(flavor.rawValue)...")
        logger("Target OpenCore path: \(ocURL.path)")
        
        // 1. Locate source kext from App Bundle or Build directory
        guard let sourceKextURL = findKextSource(for: flavor) else {
            logger("ERROR: Could not locate binary for \(flavor.kextName)")
            return false
        }
        logger("Found source driver at: \(sourceKextURL.path)")
        
        // 2. Ensure Kexts directory exists
        if !fm.fileExists(atPath: kextsURL.path) {
            do {
                try fm.createDirectory(at: kextsURL, withIntermediateDirectories: true)
                logger("Created Kexts directory.")
            } catch {
                logger("ERROR: Failed to create Kexts directory: \(error.localizedDescription)")
                return false
            }
        }
        
        // 3. Copy kext into Kexts/
        let targetKextURL = kextsURL.appendingPathComponent(flavor.kextName)
        if fm.fileExists(atPath: targetKextURL.path) {
            do {
                try fm.removeItem(at: targetKextURL)
                logger("Removed previous \(flavor.kextName)")
            } catch {
                logger("WARNING: Could not remove old kext: \(error.localizedDescription)")
            }
        }
        
        do {
            try copyDirectory(from: sourceKextURL, to: targetKextURL)
            logger("Installed \(flavor.kextName) to Kexts/")
        } catch {
            logger("ERROR: Failed to copy kext: \(error.localizedDescription)")
            return false
        }
        
        // 4. Update config.plist if requested
        if autoConfig {
            guard fm.fileExists(atPath: plistURL.path) else {
                logger("WARNING: config.plist not found, skipping OpenCore plist update.")
                return true
            }
            
            // Backup
            if backupPlist {
                let df = DateFormatter()
                df.dateFormat = "yyyyMMdd-HHmmss"
                let bakURL = ocURL.appendingPathComponent("config.plist.backup-\(df.string(from: Date()))")
                try? fm.copyItem(at: plistURL, to: bakURL)
                logger("Backed up config.plist to \(bakURL.lastPathComponent)")
            }
            
            // Modify plist
            do {
                let data = try Data(contentsOf: plistURL)
                var format = PropertyListSerialization.PropertyListFormat.xml
                guard var plist = try PropertyListSerialization.propertyList(from: data, options: .mutableContainersAndLeaves, format: &format) as? [String: Any] else {
                    logger("ERROR: Failed to parse config.plist")
                    return false
                }
                
                var kernel = (plist["Kernel"] as? [String: Any]) ?? [:]
                var add = (kernel["Add"] as? [[String: Any]]) ?? []
                
                // Remove or update existing AirportMtkWlan entry
                add.removeAll { item in
                    let b = item["BundlePath"] as? String ?? ""
                    return b == flavor.kextName
                }
                
                // Add new entry
                let newEntry: [String: Any] = [
                    "Arch": "x86_64",
                    "BundlePath": flavor.kextName,
                    "Comment": "MediaTek MT7921 / MT7922 Wi-Fi",
                    "Enabled": true,
                    "ExecutablePath": "Contents/MacOS/" + (flavor == .ethernet ? "SimpleMtkWlan" : "AirportMtkWlan"),
                    "MaxKernel": flavor.maxKernel,
                    "MinKernel": flavor.minKernel,
                    "PlistPath": "Contents/Info.plist"
                ]
                add.append(newEntry)
                
                // If installing AirportMtkWlan, disable SimpleMtkWlan to avoid conflict
                if flavor != .ethernet {
                    for i in 0..<add.count {
                        if (add[i]["BundlePath"] as? String) == "SimpleMtkWlan.kext" {
                            add[i]["Enabled"] = false
                            logger("Disabled conflicting SimpleMtkWlan.kext in config.plist")
                        }
                    }
                } else {
                    for i in 0..<add.count {
                        if (add[i]["BundlePath"] as? String) == "AirportMtkWlan.kext" {
                            add[i]["Enabled"] = false
                            logger("Disabled conflicting AirportMtkWlan.kext in config.plist")
                        }
                    }
                }
                
                kernel["Add"] = add
                
                // Ensure Kernel -> Quirks -> DisableIoMapper = true
                var quirks = (kernel["Quirks"] as? [String: Any]) ?? [:]
                quirks["DisableIoMapper"] = true
                kernel["Quirks"] = quirks
                
                plist["Kernel"] = kernel
                
                let outData = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
                try outData.write(to: plistURL)
                logger("Updated config.plist with \(flavor.kextName) entry and DisableIoMapper quirk.")
            } catch {
                logger("ERROR: Failed to update config.plist: \(error.localizedDescription)")
                return false
            }
        }
        
        logger("Installation completed successfully!")
        return true
    }
    
    // MARK: - Uninstall Driver
    
    public func uninstall(destination: EFIDestination, logger: @escaping (String) -> Void) -> Bool {
        let fm = FileManager.default
        let ocURL = URL(fileURLWithPath: destination.ocPath)
        let kextsURL = ocURL.appendingPathComponent("Kexts")
        let plistURL = ocURL.appendingPathComponent("config.plist")
        
        logger("Starting driver uninstallation...")
        
        // Remove kexts
        for name in ["AirportMtkWlan.kext", "SimpleMtkWlan.kext"] {
            let path = kextsURL.appendingPathComponent(name)
            if fm.fileExists(atPath: path.path) {
                try? fm.removeItem(at: path)
                logger("Removed \(name) from Kexts/")
            }
        }
        
        // Update config.plist
        if fm.fileExists(atPath: plistURL.path) {
            do {
                let data = try Data(contentsOf: plistURL)
                var format = PropertyListSerialization.PropertyListFormat.xml
                if var plist = try PropertyListSerialization.propertyList(from: data, options: .mutableContainersAndLeaves, format: &format) as? [String: Any] {
                    if var kernel = plist["Kernel"] as? [String: Any],
                       var add = kernel["Add"] as? [[String: Any]] {
                        for i in 0..<add.count {
                            let b = add[i]["BundlePath"] as? String ?? ""
                            if b == "AirportMtkWlan.kext" || b == "SimpleMtkWlan.kext" {
                                add[i]["Enabled"] = false
                            }
                        }
                        kernel["Add"] = add
                        plist["Kernel"] = kernel
                        let outData = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
                        try outData.write(to: plistURL)
                        logger("Disabled Wi-Fi kexts in config.plist.")
                    }
                }
            } catch {
                logger("WARNING: Could not update config.plist: \(error.localizedDescription)")
            }
        }
        
        logger("Uninstallation complete.")
        return true
    }
    
    // MARK: - Driver Loaded Check
    
    public func checkLoadedDriver() -> DriverStatus {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/kmutil")
        process.arguments = ["showloaded"]
        let pipe = Pipe()
        process.standardOutput = pipe
        try? process.run()
        process.waitUntilExit()
        
        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        if output.contains("AirportMtkWlan") {
            return DriverStatus(isLoaded: true, loadedVersion: "2.1.0", kextIdentifier: "com.flxxxxddd.AirportMtkWlan")
        } else if output.contains("SimpleMtkWlan") {
            return DriverStatus(isLoaded: true, loadedVersion: "2.1.0", kextIdentifier: "com.laobamac.SimpleMtkWlan")
        }
        return DriverStatus(isLoaded: false, loadedVersion: nil, kextIdentifier: nil)
    }
    
    // MARK: - Extension Folder Conflict Check & Fix
    
    public func hasLibraryExtensionsConflict() -> Bool {
        let fm = FileManager.default
        return fm.fileExists(atPath: "/Library/Extensions/AirportMtkWlan.kext") ||
               fm.fileExists(atPath: "/Library/Extensions/SimpleMtkWlan.kext")
    }
    
    public func purgeLibraryExtensionsConflict(logger: @escaping (String) -> Void) -> Bool {
        logger("Purging conflicting kexts from /Library/Extensions (AuxKC)...")
        let script = """
        do shell script "rm -rf /Library/Extensions/AirportMtkWlan.kext /Library/Extensions/SimpleMtkWlan.kext && kmutil clear-staging 2>&1" with administrator privileges
        """
        
        var error: NSDictionary?
        if let appleScript = NSAppleScript(source: script) {
            appleScript.executeAndReturnError(&error)
            if let error = error {
                let msg = error[NSAppleScript.errorMessage] as? String ?? "Authorization failed"
                logger("ERROR: Failed to clean /Library/Extensions: \(msg)")
                return false
            } else {
                logger("Successfully removed conflicting /Library/Extensions kexts and cleared AuxKC staging cache!")
                return true
            }
        }
        return false
    }

    // MARK: - Diagnostic Log Grabber

    public func findLogGrabberScript() -> URL? {
        let fm = FileManager.default
        var candidates: [URL] = []
        if let bundleScript = Bundle.main.resourceURL?.appendingPathComponent("mtk-grab-logs.sh") {
            candidates.append(bundleScript)
        }
        candidates.append(URL(fileURLWithPath: fm.currentDirectoryPath).appendingPathComponent("tools/mtk-grab-logs.sh"))
        candidates.append(URL(fileURLWithPath: "/Users/yash/nmx-build/wifi5/src/tools/mtk-grab-logs.sh"))
        return candidates.first(where: { fm.fileExists(atPath: $0.path) })
    }

    private func shellQuote(_ value: String) -> String {
        return "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    public func collectDiagnosticLogs(
        privileged: Bool,
        sessionLogs: [String],
        outputURL: URL,
        logger: @escaping (String) -> Void
    ) -> DiagnosticGrabResult {
        guard let scriptURL = findLogGrabberScript() else {
            let msg = "Log grabber helper (mtk-grab-logs.sh) was not found inside the app bundle or tools/."
            logger("ERROR: \(msg)")
            return DiagnosticGrabResult(success: false, archiveURL: nil, summaryText: "", message: msg)
        }

        let fm = FileManager.default
        let sessionURL = fm.temporaryDirectory.appendingPathComponent("mtk-session-\(UUID().uuidString).log")
        let sessionBody = sessionLogs.isEmpty ? "(no installer activity logged in this session)\n" : sessionLogs.joined(separator: "\n") + "\n"
        try? sessionBody.write(to: sessionURL, atomically: true, encoding: .utf8)
        defer { try? fm.removeItem(at: sessionURL) }

        logger(privileged ? "Starting full diagnostic log grab (admin privileges requested)..." : "Starting quick diagnostic log grab (standard user scope)...")

        var rawOutput = ""
        var succeeded = false

        if privileged {
            let cmd = "MTK_TARGET_USER=\(shellQuote(NSUserName())) /bin/bash \(shellQuote(scriptURL.path)) --out \(shellQuote(outputURL.path)) --session-log \(shellQuote(sessionURL.path)) 2>&1"
            let escapedForAS = cmd.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
            let appleScriptSource = "do shell script \"\(escapedForAS)\" with administrator privileges"
            var error: NSDictionary?
            if let appleScript = NSAppleScript(source: appleScriptSource) {
                let result = appleScript.executeAndReturnError(&error)
                if let error = error {
                    let msg = error[NSAppleScript.errorMessage] as? String ?? "Administrator authorization canceled or failed"
                    logger("ERROR: \(msg)")
                    return DiagnosticGrabResult(success: false, archiveURL: nil, summaryText: "", message: msg)
                }
                rawOutput = result.stringValue ?? ""
                succeeded = fm.fileExists(atPath: outputURL.path)
            }
        } else {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/bin/bash")
            task.arguments = [
                scriptURL.path,
                "--out", outputURL.path,
                "--session-log", sessionURL.path
            ]
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe
            do {
                try task.run()
                task.waitUntilExit()
                rawOutput = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                succeeded = (task.terminationStatus == 0) && fm.fileExists(atPath: outputURL.path)
            } catch {
                logger("ERROR: \(error.localizedDescription)")
                return DiagnosticGrabResult(success: false, archiveURL: nil, summaryText: "", message: error.localizedDescription)
            }
        }

        for line in rawOutput.components(separatedBy: .newlines) where !line.trimmingCharacters(in: .whitespaces).isEmpty {
            logger(line)
        }

        guard succeeded else {
            let msg = "Log collection did not produce \(outputURL.lastPathComponent)."
            logger("ERROR: \(msg)")
            return DiagnosticGrabResult(success: false, archiveURL: nil, summaryText: "", message: msg)
        }

        let summaryTask = Process()
        summaryTask.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
        summaryTask.arguments = ["-xOzf", outputURL.path, "*/00-summary.txt"]
        let summaryPipe = Pipe()
        summaryTask.standardOutput = summaryPipe
        try? summaryTask.run()
        summaryTask.waitUntilExit()
        let summaryText = String(data: summaryPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""

        logger("Saved redacted diagnostic archive to \(outputURL.path)")
        return DiagnosticGrabResult(
            success: true,
            archiveURL: outputURL,
            summaryText: summaryText,
            message: "Collected and redacted diagnostics into \(outputURL.lastPathComponent)."
        )
    }

    // MARK: - Helpers
    
    private func findKextSource(for flavor: DriverFlavor) -> URL? {
        let fm = FileManager.default
        
        // 1. Check in App bundle Resources
        if let bundleRes = Bundle.main.resourceURL?.appendingPathComponent(flavor.resourceSubpath),
           fm.fileExists(atPath: bundleRes.path) {
            return bundleRes
        }
        
        // 2. Check local build directory relative to executable or current working directory
        let searchPaths = [
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("build/Release/" + (flavor == .tahoe ? "tahoe/AirportMtkWlan.kext" : flavor == .sequoia ? "sequoia/AirportMtkWlan.kext" : "SimpleMtkWlan.kext")),
            URL(fileURLWithPath: "/Users/yash/nmx-build/wifi5/src/build/Release/" + (flavor == .tahoe ? "tahoe/AirportMtkWlan.kext" : flavor == .sequoia ? "sequoia/AirportMtkWlan.kext" : "SimpleMtkWlan.kext")),
            URL(fileURLWithPath: "/Volumes/MacExtended/Patches/" + flavor.kextName)
        ]
        
        for u in searchPaths {
            if fm.fileExists(atPath: u.path) {
                return u
            }
        }
        return nil
    }
    
    private func copyDirectory(from src: URL, to dst: URL) throws {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        task.arguments = [src.path, dst.path]
        try task.run()
        task.waitUntilExit()
        if task.terminationStatus != 0 {
            throw NSError(domain: "EFIManager", code: Int(task.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "ditto failed"])
        }
    }
    
    private func getEFIPartitionsFromDiskutil() -> [(id: String, name: String, mountPoint: String?, size: String)] {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/sbin/diskutil")
        task.arguments = ["list", "-plist"]
        let pipe = Pipe()
        task.standardOutput = pipe
        try? task.run()
        task.waitUntilExit()
        
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let plist = try? PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any],
              let allDisks = plist["AllDisksAndPartitions"] as? [[String: Any]] else {
            return []
        }
        
        var partitions: [(id: String, name: String, mountPoint: String?, size: String)] = []
        for disk in allDisks {
            if let parts = disk["Partitions"] as? [[String: Any]] {
                for part in parts {
                    let type = part["Content"] as? String ?? ""
                    if type.contains("EFI") || type.contains("FAT") {
                        let id = part["DeviceIdentifier"] as? String ?? ""
                        let name = part["VolumeName"] as? String ?? (id.isEmpty ? "EFI" : id)
                        let mount = part["MountPoint"] as? String
                        let size = ByteCountFormatter.string(fromByteCount: (part["Size"] as? Int64) ?? 0, countStyle: .file)
                        partitions.append((id: id, name: name, mountPoint: mount, size: size))
                    }
                }
            }
        }
        return partitions
    }
}
