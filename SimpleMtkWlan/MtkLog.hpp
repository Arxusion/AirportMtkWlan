//
//  MtkLog.hpp
//  SimpleMtkWlan
//
//  Persistent driver log shared by SimpleMtkWlan and AirportMtkWlan.
//

#ifndef MtkLog_hpp
#define MtkLog_hpp

#include <IOKit/IOService.h>

extern "C" void mtk_dbg_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

/* Where mtk_dbg_publish() puts the "MtkDebugLog" property (the PCI device). */
void mtk_dbg_set_nub(IOService *nub);
void mtk_dbg_publish();

#endif /* MtkLog_hpp */
