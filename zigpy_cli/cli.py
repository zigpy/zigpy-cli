from __future__ import annotations

import asyncio
import functools
import logging

import click
import coloredlogs

from zigpy_cli.const import LOG_LEVELS

LOGGER = logging.getLogger(__name__)
ROOT_LOGGER = logging.getLogger()


_LOOP: asyncio.AbstractEventLoop | None = None


def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """Return the shared event loop, creating it on first use.

    Every coroutine callback has to run on the *same* loop: the `radio` group
    callback creates the `ControllerApplication`, the subcommand then uses it, and
    `radio_cleanup` shuts it down when the context closes.
    """
    global _LOOP

    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()

    # Re-register every time: radio libraries call `asyncio.get_event_loop()` at
    # runtime, so the loop has to stay the thread's current one even if something
    # else cleared it in the meantime.
    asyncio.set_event_loop(_LOOP)

    return _LOOP


def click_coroutine(cmd):
    @functools.wraps(cmd)
    def inner(*args, **kwargs):
        loop = get_or_create_event_loop()
        return loop.run_until_complete(cmd(*args, **kwargs))

    return inner


@click.group()
@click.option("-v", "--verbose", count=True, required=False)
def cli(verbose):
    # Setup logging
    log_level = LOG_LEVELS[min(verbose, len(LOG_LEVELS) - 1)]

    level_styles = coloredlogs.DEFAULT_LEVEL_STYLES.copy()
    level_styles["trace"] = level_styles["spam"]

    LOGGER.setLevel(log_level)
    ROOT_LOGGER.setLevel(log_level)

    coloredlogs.install(
        fmt=(
            "%(asctime)s.%(msecs)03d"
            " %(hostname)s"
            " %(name)s"
            " %(levelname)s %(message)s"
        ),
        level=log_level,
        level_styles=level_styles,
        logger=ROOT_LOGGER,
    )
