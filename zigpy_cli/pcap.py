from __future__ import annotations

import datetime
import json
import logging
import sys

import click
from scapy.config import conf as scapy_conf
from scapy.layers.dot15d4 import Dot15d4  # NOQA: F401
from scapy.utils import PcapReader, PcapWriter
import zigpy.types as t

from zigpy_cli.cli import cli

from .helpers import PcapWriter as ZigpyPcapWriter

scapy_conf.dot15d4_protocol = "zigbee"

LOGGER = logging.getLogger(__name__)


@cli.group()
def pcap():
    pass


@pcap.command()
@click.argument("input", type=click.File("rb"))
@click.argument("output", type=click.File("wb"))
def fix_fcs(input, output):
    reader = PcapReader(input.raw)
    writer = PcapWriter(output.raw)

    for packet in reader:
        packet.fcs = None
        writer.write(packet)


@pcap.command()
@click.option("-o", "--output", type=click.File("wb"), required=True)
def interleave_combine(output):
    if output.name == "<stdout>":
        output = sys.stdout.buffer.raw

    writer = ZigpyPcapWriter(output)
    writer.write_header()

    while True:
        line = sys.stdin.readline()
        data = json.loads(line)
        packet = t.CapturedPacket(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            rssi=data["rssi"],
            lqi=data["lqi"],
            channel=data["channel"],
            data=bytes.fromhex(data["data"]),
        )

        writer.write_packet(packet)
