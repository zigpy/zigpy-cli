from __future__ import annotations

import hashlib
import json
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


@ota.command()
@click.pass_context
@click.option("--ota-url-root", type=str, default=None)
@click.option("--output", type=click.File("w"), default="-")
@click.argument("files", nargs=-1, type=pathlib.Path)
def generate_index(ctx, ota_url_root, output, files):
    if ctx.parent.parent.params["verbose"] == 0:
        cli.callback(verbose=1)

    ota_metadata = []

    for f in files:
        if not f.is_file():
            continue

        LOGGER.info("Parsing %s", f)
        contents = f.read_bytes()

        try:
            image, rest = parse_ota_image(contents)
        except Exception as e:
            LOGGER.error("Failed to parse: %s", e)
            continue

        if rest:
            LOGGER.error("Image has trailing data: %r", rest)
            continue

        try:
            validate_ota_image(image)
        except Exception as e:
            LOGGER.error("Image is invalid: %s", e)

        if ota_url_root is not None:
            url = f"{ota_url_root.rstrip('/')}/{f.name}"
        else:
            url = None

        metadata = {
            "binary_url": url,
            "file_version": image.header.file_version,
            "image_type": image.header.image_type,
            "manufacturer_id": image.header.manufacturer_id,
            "changelog": "",
            "checksum": f"sha3-256:{hashlib.sha3_256(contents).hexdigest()}",
        }

        if image.header.hardware_versions_present:
            metadata["min_hardware_version"] = image.header.minimum_hardware_version
            metadata["max_hardware_version"] = image.header.maximum_hardware_version

        LOGGER.info("Writing %s", f)
        ota_metadata.append(metadata)

    json.dump(ota_metadata, output, indent=4)
    output.write("\n")
