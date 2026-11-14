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
    mbuf_t m;
    bool isEmpty = true;
    bool isAwdlEmpty = true;
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

        struct ether_header *eh = mtod(m, struct ether_header *);
        bool to_awdl = false;

        if (ifq->if_awdl_enabled && ifq->if_awdl_iface != NULL) {
            if (memcmp(eh->ether_dhost, ifq->if_awdl_mac, 6) == 0 ||
                eh->ether_type == htons(0x88F0)) {
                to_awdl = true;
            } else if (eh->ether_dhost[0] == 0x33 && eh->ether_dhost[1] == 0x33) {
                // IPv6 Multicast (mDNS / AirDrop discovery): clone packet so both en0 and awdl0 receive it
                mbuf_t m_awdl = NULL;
                if (mbuf_dup(m, MBUF_DONTWAIT, &m_awdl) == 0 && m_awdl != NULL) {
                    isAwdlEmpty = false;
                    ifq->if_awdl_iface->inputPacket(m_awdl, 0, IONetworkInterface::kInputOptionQueuePacket);
                }
            }
        }

        if (to_awdl) {
            isAwdlEmpty = false;
            ifq->if_awdl_iface->inputPacket(m, 0, IONetworkInterface::kInputOptionQueuePacket);
        } else {
            isEmpty = false;
            ifq->iface->inputPacket(m, 0, IONetworkInterface::kInputOptionQueuePacket);
            if (ifq->netStat != NULL) {
                ifq->netStat->inputPackets++;
            }
        }
    }
    if (!isEmpty) {
        ifq->iface->flushInputQueue();
    }
    if (!isAwdlEmpty && ifq->if_awdl_iface != NULL) {
        ifq->if_awdl_iface->flushInputQueue();
    }
    return kIOReturnSuccess;
}

int if_input(struct _ifnet *ifq, struct mbuf_list *ml)
{
    return _fCommandGate->runAction((IOCommandGate::Action)_if_input, ifq, ml);
}

