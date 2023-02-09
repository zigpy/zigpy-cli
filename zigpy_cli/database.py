from __future__ import annotations

import asyncio
import logging
import pathlib
import re
import sqlite3
import subprocess
import tempfile

import click
import zigpy.appdb
from zigpy_znp.zigbee.application import ControllerApplication

from zigpy_cli.cli import cli

LOGGER = logging.getLogger(__name__)
DB_V_REGEX = re.compile(r"(?:_v\d+)?$")


@cli.group()
def db():
    pass


def sqlite3_split_statements(sql: str) -> list[str]:
    """
    Splits SQL into a list of statements.
    """

    statements = []
    statement = ""

    chunks = sql.strip().split(";")
    chunks_with_delimiter = [s + ";" for s in chunks[:-1]] + [chunks[-1]]

    for chunk in chunks_with_delimiter:
        statement += chunk

        if sqlite3.complete_statement(statement):
            statements.append(statement.strip())
            statement = ""

    if statement:
        LOGGER.warning("Incomplete data remains after splitting SQL: %r", statement)

    return statements


def sqlite3_recover(path: pathlib.Path) -> str:
    """
    Recovers the contents of an SQLite database as valid SQL.
    """

    return subprocess.check_output(["sqlite3", str(path), ".recover"]).decode("utf-8")


def get_table_versions(cursor) -> dict[str, str]:
    tables = {}
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")

    for (name,) in cursor:
        # The regex will always return a match
        match = DB_V_REGEX.search(name)
        assert match is not None

        tables[name] = match.group(0)

    return tables


async def test_database(path: pathlib.Path):
    """
    Opens the zigpy database with zigpy and attempts to load its contents.
    """

    with tempfile.TemporaryDirectory() as dir_name:
        dir_path = pathlib.Path(dir_name)
        db_file = dir_path / "zigbee.db"
        db_file.write_bytes(path.read_bytes())

        app = await ControllerApplication.new(
            {"database_path": str(db_file), "device": {"path": "/dev/null"}},
            auto_form=False,
            start_radio=False,
        )

        await app.shutdown()

    return app


@db.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.argument("output_path", type=click.Path())
def recover(input_path, output_path):
    if pathlib.Path(output_path).exists():
        LOGGER.error("Output database already exists: %s", output_path)
        return

    # Fetch the user version, it isn't dumped by `.recover`
    with sqlite3.connect(input_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version")
        (pragma_user_version,) = cur.fetchone()

        # Get the table suffix versions as well
        table_versions = get_table_versions(cur)

    LOGGER.info("Pragma user version is %d", pragma_user_version)

    max_table_version = max(
        int(v[2:], 10) for v in table_versions.values() if v.startswith("_v")
    )
    LOGGER.info("Maximum table version is %d", max_table_version)

    if max_table_version != pragma_user_version:
        LOGGER.warning(
            "Maximum table version is %d but the user_version is %d!",
            max_table_version,
            pragma_user_version,
        )

    if zigpy.appdb.DB_VERSION != max_table_version:
        LOGGER.warning(
            "Zigpy's current DB version is %s but the maximum table version is %s!",
            zigpy.appdb.DB_VERSION,
            max_table_version,
        )

    sql = sqlite3_recover(input_path)
    statements = sqlite3_split_statements(sql)

    # Perform the `INSERT` statements separately
    data_sql = []
    schema_sql = [f"PRAGMA user_version={max_table_version};"]

    for statement in statements:
        if statement.startswith("INSERT"):
            data_sql.append(statement)
        else:
            schema_sql.append(statement)

    assert schema_sql[-2:] == ["PRAGMA writable_schema = off;", "COMMIT;"]

    # Finally, perform the recovery
    with sqlite3.connect(output_path) as conn:
        cur = conn.cursor()

        # First create the schema
        for statement in schema_sql[:-2]:
            LOGGER.debug("Schema: %s", statement)
            cur.execute(statement)

        # Then insert data, logging errors
        for statement in data_sql:
            LOGGER.debug("Data: %s", statement)

            # Ignore internal tables
            if statement.startswith(
                (
                    'INSERT INTO "sqlite_sequence"(',
                    "CREATE TABLE IF NOT EXISTS  sqlite_sequence(",
                )
            ):
                continue

            try:
                cur.execute(statement)
            except sqlite3.IntegrityError as e:
                LOGGER.warning("Skipping %s: %r", statement, e)

        # And finally commit
        for statement in ["PRAGMA writable_schema = off;", "COMMIT;"]:
            LOGGER.debug("Postamble: %s", statement)
            cur.execute(statement)

    LOGGER.info("Finished writing database")

    # Load the database with zigpy and test it
    app = asyncio.run(test_database(pathlib.Path(output_path)))
    uninitialized_devices = [d for d in app.devices.values() if not d.is_initialized]

    LOGGER.info(
        "Recovered %d devices (%d uninitialized)",
        len(app.devices),
        len(uninitialized_devices),
    )

    for device in app.devices.values():
        LOGGER.info("%s", device)
