import pytest

from zigpy_cli.common import HEX_OR_DEC_INT


@pytest.mark.parametrize(
    "unparsed,parsed",
    [
        ("0x1234", 0x1234),
        ("1234", 1234),
        ("0xA", 0xA),
    ],
)
def test_hex_or_dec_int(unparsed, parsed):
    assert HEX_OR_DEC_INT.convert(unparsed, None, None) == parsed
    assert HEX_OR_DEC_INT.convert(parsed, None, None) == parsed
