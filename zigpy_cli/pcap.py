from __future__ import annotations

import logging

import click
from scapy.config import conf as scapy_conf
from scapy.layers.dot15d4 import Dot15d4  # NOQA: F401
from scapy.utils import PcapReader, PcapWriter

from zigpy_cli.cli import cli

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
