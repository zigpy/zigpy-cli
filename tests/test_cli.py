import asyncio

import pytest

from zigpy_cli import cli as cli_module
from zigpy_cli.cli import click_coroutine, get_or_create_event_loop


@pytest.fixture(autouse=True)
def reset_loop():
    """Keep the module-level loop from leaking between tests."""
    cli_module._LOOP = None
    asyncio.set_event_loop(None)

    yield

    if cli_module._LOOP is not None and not cli_module._LOOP.is_closed():
        cli_module._LOOP.close()

    cli_module._LOOP = None
    asyncio.set_event_loop(None)


def test_click_coroutine_without_running_loop():
    """`click_coroutine` works when no event loop exists yet.

    Python 3.14's `asyncio.get_event_loop()` raises instead of creating one.
    """
    asyncio.set_event_loop(None)

    @click_coroutine
    async def cmd(value):
        await asyncio.sleep(0)
        return value * 2

    assert cmd(21) == 42


def test_click_coroutine_reuses_the_same_loop():
    """All callbacks must share a loop: the group creates the app, the
    subcommand uses it, and the cleanup callback shuts it down."""
    loops = []

    @click_coroutine
    async def cmd():
        loops.append(asyncio.get_running_loop())

    cmd()
    cmd()

    assert loops[0] is loops[1]
    assert loops[0] is get_or_create_event_loop()


def test_get_or_create_event_loop_replaces_closed_loop():
    loop = get_or_create_event_loop()
    loop.close()

    new_loop = get_or_create_event_loop()

    assert new_loop is not loop
    assert not new_loop.is_closed()


def test_get_or_create_event_loop_reregisters_cleared_loop():
    """The loop stays registered as current even if something else clears it.

    Radio libraries call `asyncio.get_event_loop()` at runtime, which fails on
    Python 3.14 when no loop is set.
    """
    loop = get_or_create_event_loop()
    asyncio.set_event_loop(None)

    assert get_or_create_event_loop() is loop
    assert asyncio.get_event_loop() is loop
