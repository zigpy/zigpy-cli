from __future__ import annotations

import logging
import pathlib

import click
from zigpy.ota.image import ElementTagId, HueSBLOTAImage, parse_ota_image
from zigpy.ota.validators import validate_ota_image

from zigpy_cli.cli import cli

LOGGER = logging.getLogger(__name__)


@cli.group()
def ota():
    pass


@ota.command()
@click.argument("files", nargs=-1, type=pathlib.Path)
def info(files):
    for f in files:
        if not f.is_file():
            continue

        try:
            image, rest = parse_ota_image(f.read_bytes())
        except Exception as e:
            LOGGER.warning("Failed to parse %s: %s", f, e)
            continue

        if rest:
            LOGGER.warning("Image has trailing data %s: %r", f, rest)

        print(f)
        print(f"Type: {type(image)}")
        print(f"Header: {image.header}")

        if hasattr(image, "subelements"):
            print(f"Number of subelements: {len(image.subelements)}")

        try:
            result = validate_ota_image(image)
        except Exception as e:
            LOGGER.warning("Image is invalid %s: %s", f, e)
        else:
            print(f"Validation result: {result}")

        print()


@ota.command()
@click.argument("input", type=click.File("rb"))
@click.argument("output", type=click.File("wb"))
def dump_firmware(input, output):
    image, _ = parse_ota_image(input.read())

    if isinstance(image, HueSBLOTAImage):
        output.write(image.data)
    else:
        for subelement in image.subelements:
            if subelement.tag_id == ElementTagId.UPGRADE_IMAGE:
                output.write(subelement.data)
                break
        else:
            LOGGER.warning("Image has no UPGRADE_IMAGE subelements")
