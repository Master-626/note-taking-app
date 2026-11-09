"""Small SQLite store. A successful add returns only after its commit succeeds."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat

APPLICATION_ID = 0x4E4F5445
SCHEMA_VERSION = 1
_COLUMNS = [("id", "INTEGER", 0, 1), ("title", "TEXT", 1, 0),
            ("body", "TEXT", 1, 0), ("created_at", "TEXT", 1, 0)]


class StorageError(Exception):
    """The requested operation was not completed."""


def database_path(value):
    """Use a real absolute filename, never SQLite's special :memory: target."""
    return Path(value).expanduser().absolute()


def _exists(path):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise StorageError("Database must be a regular file, not a directory or symlink.")
    return True


def _validate(connection):
    application = connection.execute("PRAGMA application_id").fetchone()[0]
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if application != APPLICATION_ID or version != SCHEMA_VERSION:
        raise StorageError("Unrecognized database or unsupported schema version; no changes made.")
    columns = [(row[1], row[2], row[3], row[5])
               for row in connection.execute("PRAGMA table_info(notes)")]
    if columns != _COLUMNS:
        raise StorageError("Unexpected notes schema; no changes made.")


@contextmanager
def _connection(path, write=False):
    connection = None
    try:
        exists = _exists(path)
        if not exists and not write:
            yield None
            return
        new = False
        if not exists:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                _exists(path)
            else:
                os.close(descriptor)
                new = True
        mode = "rw" if write else "ro"
        connection = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        if new:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, "
                               "title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL)")
            connection.execute("PRAGMA application_id = %d" % APPLICATION_ID)
            connection.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        else:
            _validate(connection)
            if write:
                connection.execute("BEGIN IMMEDIATE")
        yield connection
        if write:
            connection.commit()
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise StorageError("Could not access or save notes: %s" % exc) from exc
    finally:
        if connection is not None:
            connection.close()  # An uncommitted transaction is rolled back.


def add_note(path, title, body):
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connection(path, write=True) as connection:
        cursor = connection.execute(
            "INSERT INTO notes (title, body, created_at) VALUES (?, ?, ?)",
            (title, body, created_at),
        )
        note_id = cursor.lastrowid
        # An altered schema can silently ignore or rewrite INSERT via triggers.
        # Verify the persisted values in the transaction before claiming success.
        row = connection.execute(
            "SELECT title, body, created_at FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if cursor.rowcount != 1 or row is None or tuple(row) != (title, body, created_at):
            raise StorageError("Note was not stored as requested; transaction rolled back.")
    return note_id


def list_notes(path, keyword=None):
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = [dict(row) for row in connection.execute(
            "SELECT id, title, body, created_at FROM notes ORDER BY id"
        )]
    if keyword is not None:
        query = keyword.casefold()
        rows = [row for row in rows
                if query in row["title"].casefold() or query in row["body"].casefold()]
    return rows


def get_note(path, note_id):
    with _connection(path) as connection:
        if connection is None:
            return None
        row = connection.execute(
            "SELECT id, title, body, created_at FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
    return dict(row) if row is not None else None
