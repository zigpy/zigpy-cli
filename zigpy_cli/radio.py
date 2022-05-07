from __future__ import annotations

import json
import logging
import importlib
import collections

import click
import zigpy.state
import zigpy.types
import zigpy.zdo.types

from zigpy_cli.cli import cli, click_coroutine
from zigpy_cli.common import (
    RADIO_TO_PYPI,
    HEX_OR_DEC_INT,
    RADIO_TO_PACKAGE,
    RADIO_LOGGING_CONFIGS,
)

LOGGER = logging.getLogger(__name__)


@cli.group()
@click.pass_context
@click.argument("radio", type=click.Choice(list(RADIO_TO_PACKAGE.keys())))
@click.argument("port", type=str)
@click.option("--baudrate", type=int, default=None)
@click_coroutine
async def radio(ctx, radio, port, baudrate=None):
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
    config = app_cls.SCHEMA({"device": {"path": port}})

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
@click.argument("output", type=click.File("w"))
@click.pass_obj
@click_coroutine
async def backup(app, output):
    await app.connect()
    await app.load_network_info(load_devices=True)

    obj = zigpy.state.network_state_to_json(
        network_info=app.state.network_info,
        node_info=app.state.node_info,
        source="zigpy-cli@0.0.1",
    )

    output.write(json.dumps(obj, indent=4))


@radio.command()
@click.argument("input", type=click.File("r"))
@click.pass_obj
@click_coroutine
async def restore(app, input):
    obj = json.load(input)

    network_info, node_info = zigpy.state.json_to_network_state(obj)
    network_info.network_key.tx_counter += 5000

    await app.connect()
    await app.write_network_info(network_info=network_info, node_info=node_info)


@radio.command()
@click.pass_obj
@click_coroutine
async def form(app):
    await app.startup(auto_form=True)


@radio.command()
@click.pass_obj
@click.option("--nwk", type=HEX_OR_DEC_INT, default=0x0000)
@click_coroutine
async def energy_scan(app, nwk):
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

    while True:
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
        print("------------------------------------------------")

        for channel, energies in channel_energies.items():
            count = sum(energies)
            asterisk = "*" if channel == 26 else " "

            print(
                f" - {channel:>02}{asterisk}  {count / total:>7.2%}  "
                + "#" * int(100 * count / total)
            )

        print()
