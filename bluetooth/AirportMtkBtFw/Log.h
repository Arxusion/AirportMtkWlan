//
//  Log.h
//  AirportMtkBtFw
//
//  Created by laobamac on 2026/5/30.
//  Copyright © 2026 Aswini Soni (@Arxusion). All rights reserved.
//

#ifndef Log_h
#define Log_h

#include <IOKit/IOLib.h>

#define XYLog(fmt, x...)\
do\
{\
	IOLog("%s: " fmt, "AirportMtkBtFw", ##x);\
}while(0)

#endif /* Log_h */
