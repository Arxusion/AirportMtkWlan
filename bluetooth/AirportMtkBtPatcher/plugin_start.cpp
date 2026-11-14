//
//  plugin_start.cpp
//  AirportMtkBtPatcher
//
//  Copyright © 2026 Aswini Soni (@Arxusion). All rights reserved.
//

#include <Headers/plugin_start.hpp>
#include <Headers/kern_api.hpp>

#define super IOService
OSDefineMetaClassAndStructors(PRODUCT_NAME, IOService)

bool ADDPR(startSuccess) = false;
uint32_t ADDPR(debugPrintDelay) = 0;
bool ADDPR(debugEnabled) = false;

IOService *PRODUCT_NAME::probe(IOService *provider, SInt32 *score) {
    auto service = super::probe(provider, score);
    return ADDPR(startSuccess) ? service : nullptr;
}

bool PRODUCT_NAME::start(IOService *provider) {
    if (!super::start(provider)) {
        return false;
    }
    return ADDPR(startSuccess);
}

void PRODUCT_NAME::stop(IOService *provider) {
    super::stop(provider);
}

extern "C" kern_return_t ADDPR(kern_start)(kmod_info_t *ki, void *data) {
    PE_parse_boot_argn("liludelay", &ADDPR(debugPrintDelay), sizeof(ADDPR(debugPrintDelay)));
    auto error = lilu.requestAccess();
    if (error == LiluAPI::Error::NoError) {
        error = lilu.shouldLoad(ADDPR(config).product, ADDPR(config).version, ADDPR(config).runmode,
                                ADDPR(config).disableArg, ADDPR(config).disableArgNum,
                                ADDPR(config).debugArg, ADDPR(config).debugArgNum,
                                ADDPR(config).betaArg, ADDPR(config).betaArgNum,
                                ADDPR(config).minKernel, ADDPR(config).maxKernel,
                                ADDPR(debugEnabled));
        if (error == LiluAPI::Error::NoError) {
            ADDPR(startSuccess) = true;
            ADDPR(config).pluginStart();
        }
    }
    return KERN_SUCCESS;
}

extern "C" kern_return_t ADDPR(kern_stop)(kmod_info_t *ki, void *data) {
    return ADDPR(startSuccess) ? KERN_FAILURE : KERN_SUCCESS;
}
