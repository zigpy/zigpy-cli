from __future__ import annotations

import logging
import importlib
import collections

import click
import zigpy.state
import zigpy.types
import zigpy.config as conf
import zigpy.zdo.types

from zigpy_cli.cli import cli, click_coroutine
from zigpy_cli.utils import format_bytes
from zigpy_cli.common import RADIO_TO_PYPI, RADIO_TO_PACKAGE, RADIO_LOGGING_CONFIGS

LOGGER = logging.getLogger(__name__)


@cli.group()
@click.pass_context
@click.argument("radio", type=click.Choice(list(RADIO_TO_PACKAGE.keys())))
@click.argument("port", type=str)
@click_coroutine
async def radio(ctx, radio, port):
    # Setup logging for the radio
    verbose = ctx.parent.params["verbose"]
    logging_configs = RADIO_LOGGING_CONFIGS[radio]
    logging_config = logging_configs[min(verbose, len(logging_configs) - 1)]

    for logger, level in logging_config.items():
        logging.getLogger(logger).setLevel(level)

    # Import the radio library
    module = RADIO_TO_PACKAGE[radio] + ".zigbee.application"

    try:
        radio_module = importlib.import_module(module)
    except ImportError:
        raise click.ClickException(
            f"Radio module for {radio!r} is not installed."
            f" Install it with `pip install {RADIO_TO_PYPI[radio]}`."
        )

    # Start the radio
    app_cls = radio_module.ControllerApplication
    config = app_cls.SCHEMA(
        {
            conf.CONF_DEVICE: {
                conf.CONF_DEVICE_PATH: port,
            },
        }
    )
    app = app_cls(config)

    ctx.obj = app
    ctx.call_on_close(radio_cleanup)


@click.pass_obj
@click_coroutine
async def radio_cleanup(app):
    try:
        await app.pre_shutdown()
    except RuntimeError:
        LOGGER.warning("Caught an exception when shutting down app", exc_info=True)


def dump_app_info(app):
    if app.pan_id is not None:
        print(f"PAN ID:                0x{app.pan_id:04X}")

    print(f"Extended PAN ID:       {app.extended_pan_id}")
    print(f"Channel:               {app.channel}")

    if app.channels is not None:
        print(f"Channel mask:          {list(app.channels)}")

    print(f"NWK update ID:         {app.nwk_update_id}")
    print(f"Device IEEE:           {app.ieee}")
    print(f"Device NWK:            0x{app.nwk:04X}")

    if getattr(app, "network_key", None) is not None:
        print(f"Network key:           {format_bytes(app.network_key)}")
        print(f"Network key sequence:  {app.network_key_seq}")


@radio.command()
@click.pass_obj
@click_coroutine
async def info(app):
    await app.startup(auto_form=False)
    dump_app_info(app)


@radio.command()
@click.pass_obj
@click_coroutine
async def form(app):
    await app.startup(auto_form=True)
    await app.form_network()
    dump_app_info(app)


@radio.command()
@click.pass_obj
@click_coroutine
async def energy_scan(app):
    await app.startup()
    LOGGER.info("Running scan...")

    # We compute an average over the last 5 scans
    channel_energies = collections.defaultdict(lambda: collections.deque([], maxlen=5))

    while True:
        rsp = await app.get_device(nwk=0x0000).zdo.Mgmt_NWK_Update_req(
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
