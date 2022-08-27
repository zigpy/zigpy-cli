# `zigpy-cli`

A unified command line interface for zigpy radios. The goal of this project is to allow
low-level network management from an intuitive command line interface and to group useful
Zigbee tools into a single binary.

## Installation

```console
$ pip install git+https://github.com/zigpy/zigpy-cli.git
```

## Usage

```console
$ zigpy --help
Usage: zigpy [OPTIONS] COMMAND [ARGS]...

Options:
  -v, --verbose
  --help         Show this message and exit.

Commands:
  ota
  radio
  pcap
```

**Make sure ZHA, Zigbee2MQTT, deCONZ, etc. are disabled.** Any software controlling your
radio requires exclusive access to the hardware: if both are running at once, neither will work.

# Network commands
Network commands require the radio type to be specified. See `zigpy radio --help` for the list of supported types.
If your radio requires a different baudrate than the radio library default (mainly EZSP), you must specify it as a command line option. For example, `zigpy radio --baudrate 115200 ezsp backup -`.

## Network backup

```console
$ zigpy radio deconz /dev/ttyUSB0 network backup deconz-backup.json
```

## Network restore

```console
$ zigpy radio znp /dev/ttyUSB1 network restore deconz-backup.json
```

## Reading network information

```console
$ zigpy radio znp /dev/ttyUSB0 network info
PAN ID:                0x718B
Extended PAN ID:       33:29:33:5e:30:42:64:48
Channel:               15
Channel mask:          [15]
NWK update ID:         0
Device IEEE:           00:12:4b:00:1c:ce:33:85
Device NWK:            0x0000
Network key:           cc:44:a6:4e:23:82:30:9e:35:0f:c6:6a:89:c8:dd:7d
Network key sequence:  0
```

## Forming a network

```console
$ zigpy -vvvv radio znp /dev/cu.usb* form
2021-07-12 13:24:54.764 host asyncio DEBUG Using selector: KqueueSelector
2021-07-12 13:24:54.933 host zigpy_znp.uart DEBUG Connecting to /dev/ttyUSB0 at 115200 baud
2021-07-12 13:24:54.940 host zigpy_znp.uart DEBUG Opened /dev/ttyUSB0 serial port
2021-07-12 13:24:54.941 host zigpy_znp.uart DEBUG Toggling RTS/CTS to skip CC2652R bootloader
2021-07-12 13:24:55.404 host zigpy_znp.uart DEBUG Connected to /dev/ttyUSB0 at 115200 baud
2021-07-12 13:24:55.404 host zigpy_znp.api DEBUG Waiting 1s before sending anything
2021-07-12 13:24:56.409 host zigpy_znp.api DEBUG Sending bootloader skip byte
...
PAN ID:                0xAA8A
Extended PAN ID:       35:8f:dc:b6:7a:19:33:c3
Channel:               15
Channel mask:          [15]
NWK update ID:         0
Device IEEE:           00:12:4b:00:1c:ce:33:85
Device NWK:            0x0000
Network key:           8c:2d:2d:a6:ca:95:30:04:11:6b:d5:dd:32:9e:b6:a8
Network key sequence:  0
2021-07-12 13:25:15.316 host zigpy_znp.uart DEBUG Closing serial port
```

## Performing an energy scan

```console
$ zigpy radio znp /dev/cu.usbserial-1420 energy-scan

Channel energy (mean of 1 / 5):
------------------------------------------------
 + Lower energy is better
 + Active Zigbee networks on a channel may still cause congestion
 + TX on 26 in North America may be with lower power due to regulations
 + Zigbee channels 15, 20, 25 fall between WiFi channels 1, 6, 11
 + Some Zigbee devices only join networks on channels 15, 20, and 25
------------------------------------------------
 - 11    80.00%  ################################################################################
 - 12    83.53%  ###################################################################################
 - 13    83.14%  ###################################################################################
 - 14    78.82%  ##############################################################################
 - 15    76.47%  ############################################################################
 - 16    72.16%  ########################################################################
 - 17    76.47%  ############################################################################
 - 18    75.69%  ###########################################################################
 - 19    72.16%  ########################################################################
 - 20    65.49%  #################################################################
 - 21    66.67%  ##################################################################
 - 22    70.59%  ######################################################################
 - 23    80.00%  ################################################################################
 - 24    64.31%  ################################################################
 - 25    77.25%  #############################################################################
 - 26*   81.96%  #################################################################################
```

# OTA
## Display basic information about OTA files
```console
$ zigpy ota info 10047227-1.2-TRADFRI-cv-cct-unified-2.3.050.ota.ota.signed
Header: OTAImageHeader(upgrade_file_id=200208670, header_version=256, header_length=56, field_control=<FieldControl.0: 0>, manufacturer_id=4476, image_type=16902, file_version=587531825, stack_version=2, header_string='GBL GBL_tradfri_cv_cct_unified', image_size=208766, *device_specific_file=False, *hardware_versions_present=False, *key=ImageKey(manufacturer_id=4476, image_type=16902), *security_credential_version_present=False)
Number of subelements: 1
Validation result: ValidationResult.VALID
```

## Dump embedded firmware for further analysis

```console
$ zigpy ota dump-firmware 10047227-1.2-TRADFRI-cv-cct-unified-2.3.050.ota.ota.signed - \
      | commander ebl print /dev/stdin \
      | grep 'Ember Version'
Ember Version:    6.3.1.1
```


# PCAP
## Re-calculate the FCS on a packet capture

Fixes a bug in current EmberZNet SDK releases:
```console
$ # Fix an existing capture
$ zigpy pcap fix-fcs input.pcap fixed.pcap
$ # Fix a capture from stdin and send it to stdout
$ bellows -d /dev/cu.GoControl_zigbee dump -w /dev/stdout | zigpy pcap fix-fcs - - | wireshark -k -S -i -
```
