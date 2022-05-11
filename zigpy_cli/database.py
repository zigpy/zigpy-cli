from __future__ import annotations

import logging
import pathlib
import sqlite3
import subprocess

import click

from zigpy_cli.cli import cli

LOGGER = logging.getLogger(__name__)


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
        (user_version,) = cur.fetchone()

    sql = sqlite3_recover(input_path)
    statements = sqlite3_split_statements(sql)

    # Perform the `INSERT` statements separately
    data_sql = []
    schema_sql = [f"PRAGMA user_version={user_version};"]

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

            try:
                cur.execute(statement)
            except sqlite3.IntegrityError as e:
                LOGGER.error("Failed to insert %s: %r", statement, e)

        # And finally commit
        for statement in ["PRAGMA writable_schema = off;", "COMMIT;"]:
            LOGGER.debug("Postamble: %s", statement)
            cur.execute(statement)

    LOGGER.info("Done")
