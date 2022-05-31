import logging

TRACE = logging.DEBUG - 5
logging.addLevelName(TRACE, "TRACE")


LOG_LEVELS = [logging.WARNING, logging.INFO, logging.DEBUG, TRACE]


RADIO_TO_PACKAGE = {
    "ezsp": "bellows",
    "deconz": "zigpy_deconz",
    "xbee": "zigpy_xbee",
    "zigate": "zigpy_zigate",
    "znp": "zigpy_znp",
}


RADIO_LOGGING_CONFIGS = {
    "ezsp": [
        {
            "bellows.zigbee.application": logging.INFO,
            "bellows.ezsp": logging.INFO,
        },
        {
            "bellows.zigbee.application": logging.DEBUG,
            "bellows.ezsp": logging.DEBUG,
        },
    ],
    "deconz": [
        {
            "zigpy_deconz.zigbee.application": logging.INFO,
            "zigpy_deconz.api": logging.INFO,
        },
        {
            "zigpy_deconz.zigbee.application": logging.DEBUG,
            "zigpy_deconz.api": logging.DEBUG,
        },
    ],
    "xbee": [
        {
            "zigpy_xbee.zigbee.application": logging.INFO,
            "zigpy_xbee.api": logging.INFO,
        },
        {
            "zigpy_xbee.zigbee.application": logging.DEBUG,
            "zigpy_xbee.api": logging.DEBUG,
        },
    ],
    "zigate": [
        {
            "zigpy_zigate": logging.INFO,
        },
        {
            "zigpy_zigate": logging.DEBUG,
        },
    ],
    "znp": [
        {
            "zigpy_znp": logging.INFO,
        },
        {
            "zigpy_znp": logging.DEBUG,
        },
        {
            "zigpy_znp": TRACE,
        },
    ],
}

RADIO_TO_PYPI = {name: mod.replace("_", "-") for name, mod in RADIO_TO_PACKAGE.items()}
