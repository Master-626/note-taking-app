import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from note_taking import storage
from note_taking.cli import main


@pytest.fixture
def db(tmp_path):
    return tmp_path / "notes #中文.db"


def run(db, *args):
    return CliRunner().invoke(main, ["--database", str(db), *args])


def records(db, *args):
    result = run(db, *args, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_empty_reads_do_not_create_database(db):
    assert records(db, "list") == []
    assert records(db, "search", "test") == []
    assert run(db, "show", "1").exit_code == 1
    assert not db.exists()


def test_add_list_show_roundtrip(db):
    title = "中文 [bold] literal ' ? % _"
    body = "# Heading\nExact **Markdown**\nbody only marker"
    result = run(db, "add", title, "--body", body)
    assert result.exit_code == 0, result.output
    assert "Added note #1" in result.output
    rows = records(db, "list")
    assert len(rows) == 1
    assert rows[0]["title"] == title
    assert rows[0]["body"] == body
    assert rows[0]["created_at"].endswith("+00:00")
    assert records(db, "show", "1") == rows[0]
    assert title in run(db, "show", "1").output
    assert body in run(db, "show", "1").output


def test_rich_markup_is_literal(db):
    run(db, "add", "[red]literal[/red]")
    assert "[red]literal[/red]" in run(db, "list").output


@pytest.mark.parametrize(
    "query",
    ["straße", "STRASSE", "RAẞ", "secret", "中文", "%", "_", "?", "[red]"],
)
def test_literal_unicode_search(db, query):
    run(db, "add", "Straße 中文 % _ ? [red]", "--body", "a SeCrEt body")
    run(db, "add", "Unrelated", "--body", "other text")
    assert [row["id"] for row in records(db, "search", query)] == [1]


def test_unmatched_search_has_no_sample_data(db):
    run(db, "add", "actual")
    assert records(db, "search", "Meeting Notes") == []
    assert "No matching notes." in run(db, "search", "absent").output


@pytest.mark.parametrize("args", [["add", ""], ["add", " \n\t"], ["add", "bad\x00title"],
    ["add", "Title", "--body", "bad\x00body"], ["search", ""], ["search", "  "],
    ["search", "bad\x00query"], ["show", "0"], ["show", "-1"], ["show", str(2**63)]])
def test_invalid_input_fails_without_creating_database(db, args):
    result = run(db, *args)
    assert result.exit_code != 0
    assert "Added note" not in result.output
    assert not db.exists()


def test_separate_database_files_and_duplicate_titles(db, tmp_path):
    assert run(db, "add", "same").exit_code == 0
    assert run(db, "add", "same").exit_code == 0
    assert [row["id"] for row in records(db, "list")] == [1, 2]
    assert records(tmp_path / "other.db", "list") == []


def test_failed_insert_rolls_back_and_does_not_report_success(db):
    run(db, "add", "existing")
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON notes "
            "BEGIN SELECT RAISE(ABORT, 'write blocked'); END"
        )
    result = run(db, "add", "not saved")
    assert result.exit_code == 1
    assert "Added note" not in result.output
    assert [r["title"] for r in records(db, "list")] == ["existing"]


def test_commit_failure_does_not_report_success(db, monkeypatch):
    run(db, "add", "existing")
    original = storage.sqlite3.connect

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("simulated commit failure")

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs:
                        original(*args, **dict(kwargs, factory=FailingCommit)))
    result = run(db, "add", "not committed")
    assert result.exit_code == 1
    assert "Added note" not in result.output
    assert "commit failure" in result.output
    assert [r["title"] for r in records(db, "list")] == ["existing"]


@pytest.mark.parametrize("content", [b"not SQLite\n", b""])
def test_invalid_database_bytes_preserved(db, content):
    db.write_bytes(content)
    for args in [("add", "new"), ("list",), ("search", "new"), ("show", "1")]:
        result = run(db, *args)
        assert result.exit_code == 1
        assert "Added note" not in result.output
        assert "Traceback" not in result.output
        assert db.read_bytes() == content


def test_foreign_database_is_unchanged(db):
    with sqlite3.connect(str(db)) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")
        conn.execute("INSERT INTO unrelated VALUES ('keep me')")
    before = db.read_bytes()
    assert run(db, "add", "no").exit_code == 1
    assert db.read_bytes() == before


@pytest.mark.parametrize("pragma", ["application_id = 0", "user_version = 999"])
def test_unrecognized_schema_metadata_is_rejected(db, pragma):
    run(db, "add", "before")
    with sqlite3.connect(str(db)) as conn:
        conn.execute("PRAGMA " + pragma)
    before = db.read_bytes()
    assert run(db, "add", "no").exit_code == 1
    assert run(db, "list").exit_code == 1
    assert db.read_bytes() == before


def test_broken_schema_rejected(db):
    run(db, "add", "before")
    with sqlite3.connect(str(db)) as conn:
        conn.execute("ALTER TABLE notes RENAME TO old_notes")
        conn.execute("CREATE TABLE notes (title TEXT)")
    before = db.read_bytes()
    assert run(db, "add", "no").exit_code == 1
    assert db.read_bytes() == before


def test_directory_and_parent_file_rejected(tmp_path):
    assert run(tmp_path, "add", "no").exit_code == 1
    parent = tmp_path / "file"
    parent.write_text("keep")
    assert run(parent / "notes.db", "add", "no").exit_code == 1
    assert parent.read_text() == "keep"


def test_symlink_rejected(db, tmp_path):
    target = tmp_path / "target"
    target.write_text("keep")
    try:
        db.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    assert run(db, "add", "no").exit_code == 1
    assert target.read_text() == "keep"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs unavailable")
def test_fifo_is_rejected_without_blocking(db):
    os.mkfifo(str(db))
    assert run(db, "add", "no").exit_code == 1


def test_locked_database_fails_without_success(db):
    run(db, "add", "before")
    with sqlite3.connect(str(db)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        result = run(db, "add", "not saved")
        assert result.exit_code == 1
        assert "Added note" not in result.output
    assert len(records(db, "list")) == 1


def test_default_path_is_independent_of_working_directory(tmp_path, monkeypatch):
    import click
    app_dir = tmp_path / "app-data"
    monkeypatch.setattr(click, "get_app_dir", lambda *args, **kwargs: str(app_dir))
    monkeypatch.delenv("NOTES_DATABASE", raising=False)
    first = tmp_path / "first"
    first.mkdir()
    monkeypatch.chdir(first)
    assert CliRunner().invoke(main, ["add", "default"]).exit_code == 0
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["list", "--json"])
    assert json.loads(result.output)[0]["title"] == "default"
    assert (app_dir / "notes.db").exists()
    if os.name == "posix":
        assert (app_dir / "notes.db").stat().st_mode & 0o777 == 0o600


def test_environment_path_and_explicit_override(db, tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_DATABASE", str(db))
    assert CliRunner().invoke(main, ["add", "from env"]).exit_code == 0
    assert records(db, "list")[0]["title"] == "from env"
    other = tmp_path / "explicit.db"
    assert run(other, "add", "explicit").exit_code == 0
    assert len(records(db, "list")) == 1


@pytest.mark.skipif(os.name == "nt", reason="Colon filenames are not supported on Windows")
def test_memory_named_path_is_a_real_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run(Path(":memory:"), "add", "persistent").exit_code == 0
    assert len(records(Path(":memory:"), "list")) == 1
    assert (tmp_path / ":memory:").is_file()


def test_fresh_process_roundtrip_across_working_directories(db, tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    env = dict(
        os.environ,
        PYTHONPATH=str(source),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )

    def call(cwd, *args):
        result = subprocess.run(
            [sys.executable, "-m", "note_taking.cli", "--database", str(db), *args],
            env=env,
            cwd=str(cwd),
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout
    other = tmp_path / "other cwd"
    other.mkdir()
    assert "Added note #1" in call(tmp_path, "add", "process marker", "--body", "retained body")
    assert json.loads(call(other, "list", "--json"))[0]["body"] == "retained body"
    assert json.loads(call(other, "search", "BODY", "--json"))[0]["id"] == 1
    assert json.loads(call(other, "show", "1", "--json"))["title"] == "process marker"


@pytest.mark.parametrize("trigger", [
    "BEFORE INSERT ON notes BEGIN SELECT RAISE(IGNORE); END",
    "AFTER INSERT ON notes BEGIN DELETE FROM notes WHERE id = new.id; END",
    "AFTER INSERT ON notes BEGIN UPDATE notes SET title = 'rewritten' WHERE id = new.id; END",
])
def test_silently_altered_insert_does_not_report_success(db, trigger):
    run(db, "add", "existing")
    with sqlite3.connect(str(db)) as conn:
        conn.execute("CREATE TRIGGER alter_insert " + trigger)
    result = run(db, "add", "not actually saved")
    assert result.exit_code == 1
    assert "Added note" not in result.output
    assert "rolled back" in result.output
    assert [r["title"] for r in records(db, "list")] == ["existing"]


def test_real_commit_lock_rolls_back(db):
    run(db, "add", "existing")
    with sqlite3.connect(str(db)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM notes").fetchall()
        result = run(db, "add", "uncommitted")
        assert result.exit_code == 1
        assert "locked" in result.output
        assert "Added note" not in result.output
    assert [r["title"] for r in records(db, "list")] == ["existing"]


def test_invalid_path_is_clean_error():
    result = run(Path("bad\x00file"), "add", "no")
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "Added note" not in result.output


def test_failed_initial_save_removes_empty_file_and_retries(db, monkeypatch):
    original = storage.sqlite3.connect

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("simulated commit failure")

    def fail_open(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(storage.sqlite3, "connect", fail_open)
    opened = run(db, "add", "not saved")
    assert opened.exit_code == 1
    assert "Added note" not in opened.output
    assert not db.exists()
    assert list(db.parent.glob(db.name + "-*")) == []

    monkeypatch.setattr(
        storage.sqlite3,
        "connect",
        lambda *args, **kwargs: original(*args, **dict(kwargs, factory=FailingCommit)),
    )
    committed = run(db, "add", "not saved", "--body", "y" * 1000)
    assert committed.exit_code == 1
    assert "commit failure" in committed.output
    assert "Added note" not in committed.output
    assert not db.exists()

    monkeypatch.setattr(storage.sqlite3, "connect", original)
    assert run(db, "add", "saved").exit_code == 0
    assert [row["title"] for row in records(db, "list")] == ["saved"]
    assert db.stat().st_size > 0


def test_long_titles_stay_visible_in_list_and_search(db):
    title = "START-" + ("中" * 40) + "-END-" + ("x" * 120)
    assert run(db, "add", "short neighbor").exit_code == 0
    assert run(db, "add", title, "--body", "body token").exit_code == 0
    listed = run(db, "list")
    assert listed.exit_code == 0, listed.output
    assert "short neighbor" in listed.output
    assert title in listed.output
    assert "…" not in listed.output
    found = run(db, "search", "body token")
    assert found.exit_code == 0, found.output
    assert title in found.output
    shown = run(db, "show", "2")
    assert title in shown.output


def test_non_text_value_is_a_clean_error_and_can_be_deleted(db):
    assert run(db, "add", "ok", "--body", "fine").exit_code == 0
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO notes (title, body, created_at) VALUES ('bad', X'00ff', 't')"
        )
    before = db.read_bytes()
    commands = [
        ("list",),
        ("list", "--json"),
        ("search", "ok"),
        ("show", "2"),
        ("show", "2", "--json"),
    ]
    for args in commands:
        result = run(db, *args)
        assert result.exit_code == 1, (args, result.output)
        assert "Traceback" not in result.output
        assert "Note #2" in result.output
        assert "non-text body" in result.output
        assert db.read_bytes() == before
    assert records(db, "show", "1")["body"] == "fine"
    deleted = run(db, "delete", "2")
    assert deleted.exit_code == 0, deleted.output
    assert "Deleted note #2." in deleted.output
    assert [row["title"] for row in records(db, "list")] == ["ok"]


def test_delete_removes_one_note_without_renumbering(db):
    assert run(db, "add", "first", "--body", "keep").exit_code == 0
    assert run(db, "add", "second", "--body", "gone").exit_code == 0
    assert run(db, "add", "third").exit_code == 0
    deleted = run(db, "delete", "2")
    assert deleted.exit_code == 0, deleted.output
    assert deleted.output.strip() == "Deleted note #2."
    rows = records(db, "list")
    assert [(row["id"], row["title"], row["body"]) for row in rows] == [
        (1, "first", "keep"),
        (3, "third", ""),
    ]
    added = run(db, "add", "fourth")
    assert "Added note #4" in added.output
    missing = run(db, "delete", "2")
    assert missing.exit_code == 1
    assert "does not exist" in missing.output
    assert "Deleted note" not in missing.output
    assert [row["id"] for row in records(db, "list")] == [1, 3, 4]
    assert run(db, "delete", "4").exit_code == 0
    assert db.is_file()
    assert [row["id"] for row in records(db, "list")] == [1, 3]


def test_delete_missing_database_does_not_create_file(db):
    result = run(db, "delete", "1")
    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert "Deleted note" not in result.output
    assert not db.exists()


def test_delete_commit_failure_keeps_note(db, monkeypatch):
    assert run(db, "add", "existing").exit_code == 0
    original = storage.sqlite3.connect

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("simulated commit failure")

    monkeypatch.setattr(
        storage.sqlite3,
        "connect",
        lambda *args, **kwargs: original(*args, **dict(kwargs, factory=FailingCommit)),
    )
    result = run(db, "delete", "1")
    assert result.exit_code == 1
    assert "Deleted note" not in result.output
    assert "commit failure" in result.output
    monkeypatch.setattr(storage.sqlite3, "connect", original)
    assert [row["title"] for row in records(db, "list")] == ["existing"]


def test_delete_blocked_by_trigger_rolls_back(db):
    assert run(db, "add", "keep").exit_code == 0
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "CREATE TRIGGER block_delete BEFORE DELETE ON notes "
            "BEGIN SELECT RAISE(ABORT, 'delete blocked'); END"
        )
    blocked = run(db, "delete", "1")
    assert blocked.exit_code == 1
    assert "Deleted note" not in blocked.output
    assert [row["title"] for row in records(db, "list")] == ["keep"]
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DROP TRIGGER block_delete")
        conn.execute(
            "CREATE TRIGGER restore_delete AFTER DELETE ON notes "
            "BEGIN INSERT INTO notes (id, title, body, created_at) "
            "VALUES (old.id, old.title, old.body, old.created_at); END"
        )
    restored = run(db, "delete", "1")
    assert restored.exit_code == 1
    assert "Deleted note" not in restored.output
    assert "rolled back" in restored.output
    assert [row["title"] for row in records(db, "list")] == ["keep"]


def test_delete_preserves_invalid_database(db):
    db.write_bytes(b"not SQLite\n")
    before = db.read_bytes()
    result = run(db, "delete", "1")
    assert result.exit_code == 1
    assert "Deleted note" not in result.output
    assert "Traceback" not in result.output
    assert db.read_bytes() == before
