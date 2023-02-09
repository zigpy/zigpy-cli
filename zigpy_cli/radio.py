from __future__ import annotations

import asyncio
import collections
import importlib
import importlib.util
import itertools
import json
import logging

import click
import zigpy.state
import zigpy.types
import zigpy.zdo
import zigpy.zdo.types

from zigpy_cli.cli import cli, click_coroutine
from zigpy_cli.common import HEX_OR_DEC_INT
from zigpy_cli.const import RADIO_LOGGING_CONFIGS, RADIO_TO_PACKAGE, RADIO_TO_PYPI

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
    app_cls = radio_module.ControllerApplication
    config = app_cls.SCHEMA(
        {
            "device": {"path": port},
            "backup_enabled": False,
            "database_path": database,
        }
    )

    if baudrate is not None:
        config["device"]["baudrate"] = baudrate

    app = app_cls(config)

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
@click.option("--nwk", type=HEX_OR_DEC_INT, default=0x0000)
@click.option("-n", "--num-scans", type=int, default=-1)
@click_coroutine
async def energy_scan(app, nwk, num_scans):
    await app.startup()
    LOGGER.info("Running scan...")

    # Temporarily create a zigpy device for scans not using the coordinator itself
    if nwk != 0x0000:
        app.add_device(
            nwk=nwk,
            ieee=zigpy.types.EUI64.convert("AA:AA:AA:AA:AA:AA:AA:AA"),
        )

    # We compute an average over the last 5 scans
    channel_energies = collections.defaultdict(lambda: collections.deque([], maxlen=5))

    for scan in itertools.count():
        if num_scans != -1 and scan > num_scans:
            break

        rsp = await app.get_device(nwk=nwk).zdo.Mgmt_NWK_Update_req(
            zigpy.zdo.types.NwkUpdate(
                ScanChannels=zigpy.types.Channels.ALL_CHANNELS,
                ScanDuration=0x02,
                ScanCount=1,
            )
        )

        _, scanned_channels, _, _, energy_values = rsp

        for channel, energy in zip(scanned_channels, energy_values):
            energies = channel_energies[channel]
            energies.append(energy)

        total = 0xFF * len(energies)

        print(f"Channel energy (mean of {len(energies)} / {energies.maxlen}):")
        print("------------------------------------------------")
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

    await zigpy.zdo.broadcast(
        app=app,
        command=zigpy.zdo.types.ZDOCmd.Mgmt_NWK_Update_req,
        grpid=None,
        radius=0,
        broadcast_address=zigpy.types.BroadcastAddress.ALL_DEVICES,
        NwkUpdate=zigpy.zdo.types.NwkUpdate(
            ScanChannels=zigpy.types.Channels.from_channel_list([channel]),
            ScanDuration=zigpy.zdo.types.NwkUpdate.CHANNEL_CHANGE_REQ,
            nwkUpdateId=app.state.network_info.nwk_update_id + 1,
        ),
    )

    try:
        await app.get_device(nwk=0x0000).zdo.Mgmt_NWK_Update_req(
            zigpy.zdo.types.NwkUpdate(
                ScanChannels=zigpy.types.Channels.from_channel_list([channel]),
                ScanDuration=zigpy.zdo.types.NwkUpdate.CHANNEL_CHANGE_REQ,
                nwkUpdateId=app.state.network_info.nwk_update_id + 1,
            ),
        )
    except asyncio.TimeoutError:
        pass

    while True:
        await app.load_network_info()

        LOGGER.info("Channel is currently %s", app.state.network_info.channel)

        if app.state.network_info.channel == channel:
            break

        LOGGER.info("Waiting...")
        await asyncio.sleep(3)
