from __future__ import annotations

import asyncio
import collections
import importlib
import importlib.util
import itertools
import json
import logging
import random
import sys

import click
import zigpy.backups
import zigpy.types
from zigpy.application import ControllerApplication

from zigpy_cli.cli import cli, click_coroutine
from zigpy_cli.common import CHANNELS_LIST
from zigpy_cli.const import RADIO_LOGGING_CONFIGS, RADIO_TO_PACKAGE, RADIO_TO_PYPI
from zigpy_cli.helpers import PcapWriter

LOGGER = logging.getLogger(__name__)


@cli.group()
@click.pass_context
@click.argument("radio", type=click.Choice(list(RADIO_TO_PACKAGE.keys())))
@click.argument("port", type=str)
@click.option("--baudrate", type=int, default=None)
@click.option("--database", type=str, default=None)
@click_coroutine
async def radio(ctx, radio, port, baudrate=None, database=None):
    # Setup logging for the radio
    verbose = ctx.parent.params["verbose"]
    logging_configs = RADIO_LOGGING_CONFIGS[radio]
    logging_config = logging_configs[min(verbose, len(logging_configs) - 1)]

    for logger, level in logging_config.items():
        logging.getLogger(logger).setLevel(level)

    module = RADIO_TO_PACKAGE[radio] + ".zigbee.application"

    # Catching just `ImportError` masks dependency errors and is annoying
    if importlib.util.find_spec(module) is None:
        raise click.ClickException(
            f"Radio module for {radio!r} is not installed."
            f" Install it with `pip install {RADIO_TO_PYPI[radio]}`."
        )

    # Import the radio library
    radio_module = importlib.import_module(module)

    # Start the radio
    config = {
        "device": {"path": port},
        "backup_enabled": False,
        "startup_energy_scan": False,
        "database_path": database,
        "use_thread": False,
    }

    if baudrate is not None:
        config["device"]["baudrate"] = baudrate

    app = radio_module.ControllerApplication(config)

    ctx.obj = app
    ctx.call_on_close(radio_cleanup)


@click.pass_obj
@click_coroutine
async def radio_cleanup(app):
    try:
        await app.shutdown()
    except RuntimeError:
        LOGGER.warning("Caught an exception when shutting down app", exc_info=True)


@radio.command()
@click.pass_obj
@click_coroutine
async def info(app):
    await app.connect()
    await app.load_network_info(load_devices=False)

    print(f"PAN ID:                0x{app.state.network_info.pan_id:04X}")
    print(f"Extended PAN ID:       {app.state.network_info.extended_pan_id}")
    print(f"Channel:               {app.state.network_info.channel}")
    print(f"Channel mask:          {list(app.state.network_info.channel_mask)}")
    print(f"NWK update ID:         {app.state.network_info.nwk_update_id}")
    print(f"Device IEEE:           {app.state.node_info.ieee}")
    print(f"Device NWK:            0x{app.state.node_info.nwk:04X}")
    print(f"Network key:           {app.state.network_info.network_key.key}")
    print(f"Network key sequence:  {app.state.network_info.network_key.seq}")
    print(f"Network key counter:   {app.state.network_info.network_key.tx_counter}")


@radio.command()
@click.option("-z", "--zigpy-format", is_flag=True, type=bool, default=False)
@click.option(
    "--i-understand-i-can-update-eui64-only-once-and-i-still-want-to-do-it",
    is_flag=True,
    type=bool,
    default=False,
)
@click.argument("output", type=click.File("w"), default="-")
@click.pass_obj
@click_coroutine
async def backup(
    app,
    zigpy_format,
    i_understand_i_can_update_eui64_only_once_and_i_still_want_to_do_it,
    output,
):
    await app.connect()

    backup = await app.backups.create_backup(load_devices=True)

    if i_understand_i_can_update_eui64_only_once_and_i_still_want_to_do_it:
        backup.network_info.stack_specific.setdefault("ezsp", {})[
            "i_understand_i_can_update_eui64_only_once_and_i_still_want_to_do_it"
        ] = True

    if zigpy_format:
        obj = backup.as_dict()
    else:
        obj = backup.as_open_coordinator_json()

    output.write(json.dumps(obj, indent=4) + "\n")


@radio.command()
@click.argument("input", type=click.File("r"))
@click.option("-c", "--frame-counter-increment", type=int, default=5000)
@click.pass_obj
@click_coroutine
async def restore(app, frame_counter_increment, input):
    obj = json.load(input)
    backup = zigpy.backups.NetworkBackup.from_dict(obj)

    await app.connect()
    await app.backups.restore_backup(backup, counter_increment=frame_counter_increment)


@radio.command()
@click.pass_obj
@click_coroutine
async def form(app):
    await app.connect()
    await app.form_network()


@radio.command()
@click.pass_obj
@click_coroutine
async def reset(app):
    await app.connect()
    await app.reset_network_info()


@radio.command()
@click.pass_obj
@click.option("-t", "--join-time", type=int, default=250)
@click_coroutine
async def permit(app, join_time):
    await app.startup(auto_form=True)
    await app.permit(join_time)
    await asyncio.sleep(join_time)


@radio.command()
@click.pass_obj
@click.option("-n", "--num-scans", type=int, default=-1)
@click_coroutine
async def energy_scan(app, num_scans):
    await app.startup()
    LOGGER.info("Running scan...")

    # We compute an average over the last 5 scans
    channel_energies = collections.defaultdict(lambda: collections.deque([], maxlen=5))

    for scan in itertools.count():
        if num_scans != -1 and scan > num_scans:
            break

        results = await app.energy_scan(
            channels=zigpy.types.Channels.ALL_CHANNELS, duration_exp=2, count=1
        )

        for channel, energy in results.items():
            energies = channel_energies[channel]
            energies.append(energy)

        total = 0xFF * len(energies)

        print(f"Channel energy (mean of {len(energies)} / {energies.maxlen}):")
        print("------------------------------------------------")
        print(" ! Different radios compute channel energy differently")
        print()
        print(" + Lower energy is better")
        print(" + Active Zigbee networks on a channel may still cause congestion")
        print(" + TX on 26 in North America may be with lower power due to regulations")
        print(" + Zigbee channels 15, 20, 25 fall between WiFi channels 1, 6, 11")
        print(" + Some Zigbee devices only join networks on channels 15, 20, and 25")
        print(" + Current channel is enclosed in [square brackets]")
        print("------------------------------------------------")

        for channel, energies in channel_energies.items():
            count = sum(energies)
            asterisk = "*" if channel == 26 else " "

            if channel == app.state.network_info.channel:
                bracket_open = "["
                bracket_close = "]"
            else:
                bracket_open = " "
                bracket_close = " "

            print(
                f" - {bracket_open}{channel:>02}{asterisk}{bracket_close}"
                + f"   {count / total:>7.2%}  "
                + "#" * int(100 * count / total)
            )

        print()


@radio.command()
@click.pass_obj
@click.option("-c", "--channel", type=int)
@click_coroutine
async def change_channel(app, channel):
    await app.startup()

    LOGGER.info("Current channel is %s", app.state.network_info.channel)

    await app.move_network_to_channel(channel)


@radio.command()
@click.pass_obj
@click.option("-r", "--channel-hop-randomly", is_flag=True, type=bool, default=False)
@click.option(
    "-c",
    "--channels",
    type=CHANNELS_LIST,
    default=zigpy.types.Channels.ALL_CHANNELS,
)
@click.option("-p", "--channel-hop-period", type=float, default=5.0)
@click.option("-o", "--output", type=click.File("wb"), required=True)
@click.option("--interleave", is_flag=True, type=bool, default=False)
@click_coroutine
async def packet_capture(
    app,
    channel_hop_randomly,
    channels,
    channel_hop_period,
    output,
    interleave,
):
    if output.name == "<stdout>" and not interleave:
        output = sys.stdout.buffer.raw

    if not channel_hop_randomly:
        channels_iter = itertools.cycle(channels)
    else:

        def channels_iter_func():
            while True:
                yield random.choice(tuple(channels))

        channels_iter = channels_iter_func()

    if app._packet_capture is ControllerApplication._packet_capture:
        raise click.ClickException("Packet capture is not supported by this radio")

    await app.connect()

    if not interleave:
        writer = PcapWriter(output)
        writer.write_header()

    async with asyncio.TaskGroup() as tg:
        channel_hopper_task = None

        async def channel_hopper():
            for channel in channels_iter:
                await asyncio.sleep(channel_hop_period)
                LOGGER.debug("Changing channel to %s", channel)
                await app.packet_capture_change_channel(channel)

        async for packet in app.packet_capture(channel=next(channels_iter)):
            if channel_hopper_task is None:
                channel_hopper_task = tg.create_task(channel_hopper())

            LOGGER.debug("Got a packet %s", packet)

            if not interleave:
                writer.write_packet(packet)
            else:
                # To do line interleaving, encode the packets as JSON
                output.write(
                    json.dumps(
                        {
                            "timestamp": packet.timestamp.isoformat(),
                            "rssi": packet.rssi,
                            "lqi": packet.lqi,
                            "channel": packet.channel,
                            "data": packet.data.hex(),
                        }
                    ).encode("ascii")
                    + b"\n"
                )
                output.flush()


@radio.command()
@click.pass_obj
@click.option("-r", "--randomize", is_flag=True, type=bool, default=False)
@click.option("-u", "--unfiltered", is_flag=True, type=bool, default=False)
@click.option("-n", "--num-scans", type=int, default=-1)
@click.option("-d", "--duration-exponent", type=int, default=4)
@click.option(
    "-c",
    "--channels",
    type=CHANNELS_LIST,
    default=zigpy.types.Channels.ALL_CHANNELS,
)
@click_coroutine
async def network_scan(
    app, randomize, unfiltered, num_scans, duration_exponent, channels
):
    if app._network_scan is ControllerApplication._network_scan:
        raise click.ClickException("Network scan is not supported by this radio")

    await app.startup()
    LOGGER.info("Running scan...")

    seen_beacons = set()

    if randomize:

        def channels_iter_func():
            while True:
                yield random.choice(tuple(channels))

        channels_iter = channels_iter_func()
    else:
        channels_iter = itertools.cycle(channels)

    for scan in itertools.count():
        channel = next(channels_iter)

        if num_scans != -1 and scan > num_scans:
            break

        print(f"Scanning channel {channel}\r", end="", flush=True)

        async for network in app.network_scan(
            channels=zigpy.types.Channels.from_channel_list([channel]),
            duration_exp=duration_exponent,
        ):
            key = network.replace(lqi=None, rssi=None)

            if key in seen_beacons:
                continue

            seen_beacons.add(key)

            print(
                f"channel: {network.channel}, "
                f"network: {network.pan_id} ({network.extended_pan_id}), "
                f"permitting joins: {int(network.permit_joining)}, "
                f"nwk update id: {network.nwk_update_id}, "
                f"lqi: {network.lqi:>4}, "
                f"rssi: {network.rssi:>3}"
            )
