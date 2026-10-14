//
//  MtkDriverInfo.hpp
//  SimpleMtkWlan
//
//  Created by laobamac (王孝慈) on 2026/5/23.
//  Copyright © 2026 laobamac (王孝慈). All rights reserved.
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

#ifndef MtkDriverInfo_h
#define MtkDriverInfo_h

class MtkDriverInfo {
    
public:
    
    virtual const char *getFirmwareVersion() = 0;
    
    virtual int16_t getBSSNoise() = 0;
    
    virtual bool is5GBandSupport() = 0;
    
    virtual int getTxNSS() = 0;
    
    virtual const char *getFirmwareName() = 0;
    
    virtual UInt32 supportedFeatures() = 0;

    virtual const char *getFirmwareCountryCode() = 0;

    virtual uint32_t getTxQueueSize() = 0;

    // Rate of the last received unicast data frame, 0 if unknown
    virtual uint32_t getRxRateKbps() = 0;

    // MCS of the last received data frame (HT: 0-15, VHT: 0-9), -1 if unknown
    virtual int getRxRateMcs() = 0;
};

#endif /* MtkDriverInfo_h */
