//
//  MtkMwx.hpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/5/17.
//  Copyright © 2026 laobamac (王孝慈). All rights reserved.
//

/*
 * MediaTek MT7922 HAL for SimpleMtkWlan.
 *
 * The driver body is ported from OpenBSD if_mwx.  This header only exposes
 * the SimpleMtkWlan HAL boundary; OpenBSD driver internals stay in MtkMwx.cpp.
 */

#ifndef MtkMwx_hpp
#define MtkMwx_hpp

#include <compat.h>
#include <HAL/MtkHalService.hpp>
#include <HAL/MtkDriverInfo.hpp>
#include <HAL/MtkDriverController.hpp>

struct mwx_softc;
struct pci_attach_args;

class MtkMwx : public MtkHalService, MtkDriverInfo, MtkDriverController {
    OSDeclareDefaultStructors(MtkMwx)

public:
    bool attach(IOPCIDevice *device) override;
    void detach(IOPCIDevice *device) override;
    IOReturn enable(IONetworkInterface *interface) override;
    IOReturn disable(IONetworkInterface *interface) override;
    struct ieee80211com *get80211Controller() override;
    MtkDriverInfo *getDriverInfo() override;
    MtkDriverController *getDriverController() override;
    void free() override;

    const char *getFirmwareVersion() override;
    int16_t getBSSNoise() override;
    bool is5GBandSupport() override;
    bool isMT7922() override;
    int getTxNSS() override;
    const char *getFirmwareName() override;
    UInt32 supportedFeatures() override;
    const char *getFirmwareCountryCode() override;
    uint32_t getTxQueueSize() override;
    uint32_t getRxRateKbps() override;
    int getRxRateMcs() override;

    void clearScanningFlags() override;
    void debugPoll() override;
#if defined(MTK_NATIVE_AWDL) && defined(AIRPORT_WCL) && __IO80211_TARGET == __MAC_26_0
    IOReturn transmitAwdlAnnouncement(const uint8_t *, size_t, MtkAwdl::TxKind, uint8_t) override;
    uint8_t getAwdlChannel(bool &allowed) override;
    bool readAwdlAnnouncementCompletions(MtkAwdl::AnnouncementCompletions &) override;
    IOReturn setAwdlMacAddress(const uint8_t *, bool) override;
#endif
    void publishHealthDiagnostics();
    void suspend() override;
    void resume() override;
    IOReturn systemPower(bool suspend);
    void systemPowerStats(uint32_t out[9]);
    IOReturn setCountryCode(const char *cc) override;
    IOReturn setMulticastList(IOEthernetAddress *addr, int count) override;
#ifdef AIRPORT_WCL
    IOReturn setScanHomeAwayTime(uint32_t timeMs) override;
#endif

    static bool mwx_match(IOPCIDevice *device);

    IOEthernetController *mwxController();
    int mwxSleepNsec(void *ident, int priority, const char *wmesg, uint64_t timo);
    void mwxWakeup(void *ident);

private:
    void releaseAll();

    bool taskQueueOwned;
    struct mwx_softc *com;
    struct pci_attach_args *pci;
};

#endif /* MtkMwx_hpp */
