"""Small SQLite store. A successful add returns only after its commit succeeds."""

import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

APPLICATION_ID = 0x4E4F5445
SCHEMA_VERSION = 1
_COLUMNS = [("id", "INTEGER", 0, 1), ("title", "TEXT", 1, 0),
            ("body", "TEXT", 1, 0), ("created_at", "TEXT", 1, 0)]
_TEXT_FIELDS = ("title", "body", "created_at")


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


def _record(row):
    record = dict(row)
    note_id = record.get("id")
    for field in _TEXT_FIELDS:
        if not isinstance(record.get(field), str):
            raise StorageError(
                "Note #%s has a non-text %s; no changes made." % (note_id, field)
            )
    return record


def _discard_uncommitted_file(path, identity):
    """Drop an empty file created by this process when its first commit did not finish.

    A committed SQLite database is never zero bytes, so this cannot remove saved notes.
    """
    if identity is None:
        return
    try:
        current = path.lstat()
    except OSError:
        return
    if (not stat.S_ISREG(current.st_mode) or current.st_size != 0
            or (current.st_dev, current.st_ino) != identity):
        return
    try:
        path.unlink()
    except OSError:
        pass


@contextmanager
def _connection(path, write=False, create=False):
    connection = None
    new = False
    created_identity = None
    committed = False
    try:
        exists = _exists(path)
        if not exists and not (write and create):
            yield None
            return
        if not exists:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                _exists(path)
            else:
                info = os.fstat(descriptor)
                created_identity = (info.st_dev, info.st_ino)
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
        if write and connection is not None:
            connection.commit()
            committed = True
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise StorageError("Could not access or save notes: %s" % exc) from exc
    finally:
        if connection is not None:
            connection.close()  # An uncommitted transaction is rolled back.
        if new and not committed:
            _discard_uncommitted_file(path, created_identity)


def add_note(path, title, body):
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connection(path, write=True, create=True) as connection:
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


def delete_note(path, note_id):
    """Delete one note after commit. A missing database is not created."""
    with _connection(path, write=True) as connection:
        if connection is None:
            raise StorageError("Note #%d does not exist." % note_id)
        existing = connection.execute(
            "SELECT id FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if existing is None:
            raise StorageError("Note #%d does not exist." % note_id)
        cursor = connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        remaining = connection.execute(
            "SELECT id FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        # Triggers can ignore the DELETE or put the row back. Success requires
        # the row to be gone inside this transaction, which rolls back on error.
        if cursor.rowcount != 1 or remaining is not None:
            raise StorageError("Note was not deleted; transaction rolled back.")
    return note_id


def list_notes(path, keyword=None):
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = [_record(row) for row in connection.execute(
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
    return _record(row) if row is not None else None
