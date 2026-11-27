//
//  _mbuf.cpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/4/21.
//  Copyright © 2026 laobamac (王孝慈). All rights reserved.
//

//
//  _mbuf.cpp
//  SimpleMtkWlan
//
//  Created by qcwap on 2020/6/14.
//  Copyright © 2020 钟先耀. All rights reserved.
//
/*
* Copyright (C) 2020  钟先耀
*
* This program is free software; you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation; either version 2 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*/

#include <HAL/MtkPerf.hpp>
#include <sys/_mbuf.h>
extern "C" {
#include <net/bpf.h>
#include <net/ethernet.h>
}
#include <IOKit/IOCommandGate.h>

extern IOCommandGate *_fCommandGate;

struct network_header {
    char pad[0x48];
};

static IOReturn _if_input(OSObject *target, void *arg0, void *arg1, void *arg2, void *arg3)
{
#if MTK_PERF
    MpTimer perf(mp_rx_if_input_samples);
#endif
    mbuf_t m;
    bool isEmpty = true;
    struct _ifnet *ifq = (struct _ifnet *)arg0;
    struct mbuf_list *ml = (struct mbuf_list *)arg1;
    
    /* Detach before transferring ownership. IOKit requires nextpkt == NULL,
     * and the driver must not walk a packet after inputPacket consumes it. */
    while ((m = ml_dequeue(ml)) != NULL) {
        if (ifq->iface == NULL) {
            panic("%s ifq->iface == NULL!!!\n", __FUNCTION__);
            break;
        }
        if (m == NULL) {
            XYLog("%s m == NULL!!!\n", __FUNCTION__);
            continue;
        }

        isEmpty = false;
#if MTK_PERF
        // Count infrastructure delivery. AWDL has its own native queues.
        mp_add(mp_rx_bsd_packets);
        mp_add(mp_rx_bsd_bytes, mbuf_pkthdr_len(m));
        UInt32 accepted =
#endif
        ifq->iface->inputPacket(m, 0, IONetworkInterface::kInputOptionQueuePacket);
#if MTK_PERF
        mp_add(mp_rx_bsd_return_packets, accepted);
#endif
        if (ifq->netStat != NULL) {
            ifq->netStat->inputPackets++;
        }
    }
    if (!isEmpty) {
#if MTK_PERF
        MpTimer flush(mp_rx_bsd_flush_samples);
        UInt32 flushed =
#endif
        ifq->iface->flushInputQueue();
#if MTK_PERF
        mp_add(mp_rx_bsd_flush_return, flushed);
#endif
    }
    return kIOReturnSuccess;
}

int if_input(struct _ifnet *ifq, struct mbuf_list *ml)
{
    return _fCommandGate->runAction((IOCommandGate::Action)_if_input, ifq, ml);
}

