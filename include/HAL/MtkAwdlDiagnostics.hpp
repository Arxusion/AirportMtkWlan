#pragma once

#include <IOKit/IOLib.h>

extern unsigned int mtk_awdl_diagnostics_armed;

static inline bool mtk_awdl_diagnostics_enabled()
{
    return __atomic_load_n(&mtk_awdl_diagnostics_armed, __ATOMIC_ACQUIRE) != 0;
}

#if defined(AIRPORT_WCL) && __IO80211_TARGET == __MAC_26_0
class IOEthernetController;
void mtkAwdlObserveAction(IOEthernetController *, mbuf_t, uint32_t channel, int32_t rssi);
void mtkAwdlObserveData(IOEthernetController *, mbuf_t, uint32_t);
#endif
