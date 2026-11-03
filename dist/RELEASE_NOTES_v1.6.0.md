## AirportMtkWlan v1.6.0 (Pure WPA3-Personal SAE / Dragonfly Mode)

AirportMtkWlan v1.6.0 introduces native support for **Pure WPA3-Personal SAE (Simultaneous Authentication of Equals)** without requiring fallback to WPA2-PSK transition mode, implementing the full IEEE 802.11-2016 / RFC 7664 Dragonfly Key Exchange protocol directly inside the driver.

### What's Changed in v1.6.0

- **Dragonfly Key Exchange Engine (NIST P-256 / Group 19)**:
  - Added Jacobian projective elliptic curve coordinate arithmetic with Solinas prime reduction.
  - Constant-time scalar multiplication and modular inversion via Fermat's Little Theorem.
  - Implemented Hunting-and-Pecking Password-Element ($PWE$) derivation with SHA-256 HMAC and lexicographical MAC address salting.
  - Full Commit frame generation, AP Commit token validation, and Confirm token generation/verification.
- **Pure WPA3-Personal (AKM 8 / `00-0F-AC:8`)**:
  - Full parsing and serialization of AKM Suite 8 in RSN information elements.
  - Preserved `APPLE80211_AUTHTYPE_WPA3_SAE` in the Skywalk WCL join flow for pure WPA3 networks while preserving seamless automatic WPA2-PSK transition fallback for mixed networks.
- **Mandatory Protected Management Frames (PMF / 802.11w)**:
  - Enforced `MFPC = 1, MFPR = 1` in RSN Capabilities when connecting to WPA3-SAE networks.
  - Wired BIP-CMAC-128 IGTK management encryption to MT7921/MT7922 hardware encryption registers.
- **Pairwise Master Key ($PMK$) & PMKID Derivation**:
  - Direct derivation of PMK and PMKID from Dragonfly shared secret $K_x$, feeding directly into SHA-256 KDF for the standard 4-Way Handshake.
- **Updated Native Installer App v1.6.0**:
  - Bundled with all v1.6.0 binaries for automated EFI detection and OpenCore injection.

### Binaries Included

| Asset | Target OS | Kernel Version Range |
| :--- | :--- | :--- |
| `AirportMtkWlan-Tahoe-v1.6.0-RELEASE.zip` | macOS 26 Tahoe | `25.0.0` - `26.99.99` |
| `AirportMtkWlan-Sequoia-v1.6.0-RELEASE.zip` | macOS 15 Sequoia (15.2+) | `24.2.0` - `24.99.99` |
| `AirportMtkWlan-Installer-v1.6.0.zip` | macOS 26 / 15 GUI Installer App | `24.0.0`+ |
| `SimpleMtkWlan-v1.6.0-RELEASE.zip` | macOS Sonoma / Ventura / Monterey / any | `*` |
