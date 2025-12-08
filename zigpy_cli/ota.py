from __future__ import annotations

import collections
import hashlib
import json
import logging
import pathlib
import subprocess

import click
import zigpy.types as t
from zigpy.ota.image import ElementTagId, HueSBLOTAImage, parse_ota_image
from zigpy.ota.validators import validate_ota_image
from zigpy.types.named import _hex_string_to_bytes
from zigpy.util import convert_install_code as zigpy_convert_install_code

from zigpy_cli.cli import cli
from zigpy_cli.common import HEX_OR_DEC_INT

LOGGER = logging.getLogger(__name__)


def convert_install_code(text: str) -> t.KeyData:
    code = _hex_string_to_bytes(text)
    key = zigpy_convert_install_code(code)

    if key is None:
        raise ValueError(f"Invalid install code: {text!r}")

    return key


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
            "file_size": len(contents),
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

    json.dump({"firmwares": ota_metadata}, output, indent=4)
    output.write("\n")


@ota.command()
@click.pass_context
@click.option(
    "--add-network-key", "network_keys", type=t.KeyData.convert, multiple=True
)
@click.option(
    "--add-install-code", "install_codes", type=convert_install_code, multiple=True
)
@click.option("--fill-byte", type=HEX_OR_DEC_INT, default=0xAB)
@click.option(
    "--output-root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=pathlib.Path),
    required=True,
)
@click.argument("files", nargs=-1, type=pathlib.Path)
def reconstruct_from_pcaps(
    ctx, network_keys, install_codes, fill_byte, output_root, files
):
    for code in install_codes:
        print(f"Using key derived from install code: {code}")

    network_keys = (
        [
            # ZigBeeAlliance09
            t.KeyData.convert("5A:69:67:42:65:65:41:6C:6C:69:61:6E:63:65:30:39"),
            # Z2M default
            t.KeyData.convert("01:03:05:07:09:0B:0D:0F:00:02:04:06:08:0A:0C:0D"),
        ]
        + list(network_keys)
        + list(install_codes)
    )

    keys = "\n".join(
        [f'"{k}","Normal","Network Key {i + 1}"' for i, k in enumerate(network_keys)]
    )
    packets = []

    for f in files:
        proc = subprocess.run(
            [
                "tshark",
                "-o",
                f"uat:zigbee_pc_keys:{keys}",
                "-r",
                str(f),
                "-T",
                "json",
            ],
            capture_output=True,
        )

        obj = json.loads(proc.stdout)
        packets.extend(p["_source"]["layers"] for p in obj)

    ota_sizes = {}
    ota_chunks = collections.defaultdict(set)

    for packet in packets:
        if "zbee_zcl" not in packet:
            continue

        # Ignore non-OTA packets
        if packet["zbee_aps"]["zbee_aps.cluster"] != "0x0019":
            continue

        if (
            packet.get("zbee_zcl", {})
            .get("Payload", {})
            .get("zbee_zcl_general.ota.status")
            == "0x00"
        ):
            zcl = packet["zbee_zcl"]["Payload"]
            image_version = zcl["zbee_zcl_general.ota.file.version"]
            image_type = zcl["zbee_zcl_general.ota.image.type"]
            image_manuf_code = zcl["zbee_zcl_general.ota.manufacturer_code"]

            image_key = (image_version, image_type, image_manuf_code)

            if "zbee_zcl_general.ota.image.size" in zcl:
                image_size = int(zcl["zbee_zcl_general.ota.image.size"])
                ota_sizes[image_key] = image_size
            elif "zbee_zcl_general.ota.image.data" in zcl:
                offset = int(zcl["zbee_zcl_general.ota.file.offset"])
                data = bytes.fromhex(
                    zcl["zbee_zcl_general.ota.image.data"].replace(":", "")
                )

                ota_chunks[image_key].add((offset, data))

    unknown_sizes = set()

    for key in ota_chunks:
        if key in ota_sizes:
            continue

        unknown_sizes.add(key)
        ota_sizes[key] = max(offset + len(data) for offset, data in ota_chunks[key])
        LOGGER.error(
            "Image size for %s not captured, assuming size %s", key, ota_sizes[key]
        )

    for image_key, image_size in ota_sizes.items():
        image_version, image_type, image_manuf_code = image_key
        print(
            f"Constructing image type={image_type}, version={image_version}"
            f", manuf_code={image_manuf_code}: {image_size} bytes"
        )

        buffer = [None] * image_size

        for offset, chunk in sorted(ota_chunks[image_key]):
            current_value = buffer[offset : offset + len(chunk)]

            if (
                all(c is not None for c in buffer[offset : offset + len(chunk)])
                and current_value != chunk
            ):
                LOGGER.error(
                    f"Inconsistent {len(chunk)} bytes starting at offset"
                    f" 0x{offset:08X}: was {current_value}, now {chunk}"
                )

            buffer[offset : offset + len(chunk)] = chunk

        missing_indices = [o for o, v in enumerate(buffer) if v is None]
        missing_ranges = []

        # For readability, combine the list of missing indices into a list of ranges
        if missing_indices:
            start = missing_indices[0]
            count = 0

            for i in missing_indices[1:]:
                if i == start + count + 1:
                    count += 1
                else:
                    missing_ranges.append((start, count + 1))
                    start = i
                    count = 0

            if count > 0:
                missing_ranges.append((start, count + 1))

        for start, count in missing_ranges:
            LOGGER.error(
                f"Missing {count} bytes starting at offset 0x{start:08X}:"
                f" filling with 0x{fill_byte:02X}"
            )
            buffer[start : start + count] = [fill_byte] * count

        filename = output_root / (
            f"ota_t{image_type}_m{image_manuf_code}_v{image_version}"
            f"{'_unk_size' if image_key in unknown_sizes else ''}"
            f"{'_partial' if missing_ranges else ''}.ota"
        )

        output_root.mkdir(exist_ok=True)
        filename.write_bytes(bytes(buffer))

        info.callback([filename])
