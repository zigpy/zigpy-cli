from __future__ import annotations

import logging
import importlib

import click
import zigpy.config as conf

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
    await app.startup(auto_form=False)

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
def info(app):
    dump_app_info(app)


@radio.command()
@click.pass_obj
@click_coroutine
async def form(app):
    await app.form_network()
    dump_app_info(app)
