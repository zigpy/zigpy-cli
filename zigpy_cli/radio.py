from __future__ import annotations

import json
import logging
import importlib

import click
import zigpy.state
import zigpy.config as conf

from zigpy_cli.cli import cli, click_coroutine
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
    network_info.network_key_counter += 5000

    await app.connect()
    await app.write_network_info(network_info=network_info, node_info=node_info)


@radio.command()
@click.pass_obj
@click_coroutine
async def form(app):
    await app.connect()
    await app.startup(auto_form=True)
    await app.form_network()
