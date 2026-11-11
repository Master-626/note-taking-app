# Note Taking App

## 中文简介

本地 SQLite 笔记命令行工具，支持 Python 3.8 及以上，不需要账号或服务器。可以新增、列出、查看、按字面量搜索和删除笔记。数据默认写在用户应用数据目录的 `notes.db`；把全局选项 `--database` 放在子命令前，或设置环境变量 `NOTES_DATABASE`，即可改用别的文件。

```bash
python -m pip install .
notes add "会议记录" --body "核对发布清单"
notes list
notes search 发布
notes show 1
notes delete 1
python -m pip install ".[dev]"
python -m ruff check .
python -m pytest
```

首次保存若在提交前失败，本次新建的空数据库文件会被删掉，同一路径可以重试。已经存在的无效文件不会被覆盖。删除笔记不会重排其他笔记的 ID。

## English

A small, local SQLite note CLI for Python 3.8+. Create notes, read them later,
find literal text in their titles or bodies, and delete a note by ID. No
account or server is needed.

## Status

Version 0.2.0 replaces the original prototype's simulated success messages and
fixed example list with real persistence. The original 0.1.0 `add` command did
not store notes, so there is no saved 0.1.0 database to migrate or recover.
Version 0.3.0 adds `delete` and keeps a failed first save from leaving an
unusable empty database file.

Supported features:

- Save a title and optional plain-text body, with a stable ID and UTC creation time.
- List and read saved notes across separate invocations and working directories.
- Search titles and bodies using Unicode-aware, case-insensitive literal substrings.
- Read complete records as JSON.
- Delete one note by ID without renumbering the notes that remain.

Markdown is stored as text, not rendered. Tags, folders, pinning, editing,
import/export, PDF/HTML conversion, and indexed full-text search are not
implemented. Search scans the stored notes and is intended for small local
collections. The CLI does not encrypt, synchronize, or back up your notes.

## Install

```bash
git clone https://github.com/Master-626/note-taking-app.git
cd note-taking-app
python -m pip install .
```

## Use

```bash
notes add "Meeting Notes" --body "Discuss the launch checklist."
notes list
notes search launch
notes show 1
notes show 1 --json
notes list --json
notes delete 1
```

An `add` or `delete` command reports success only after SQLite commits the
change. Unknown IDs, invalid input, unreadable/locked databases, and save or
delete failures return a nonzero exit code. A search with no matches returns an
empty result, not an error. Titles and search terms must not be blank. NUL
characters are not accepted. Human-readable lists show each title in full,
widening past the terminal width when a title would otherwise be cut off.

## Options

Global options belong before the command name:

- `--database PATH` — SQLite file for this invocation. Overrides `NOTES_DATABASE`. Default: `notes.db` in the user app-data directory described below.
- `--version` — print the program version and exit.
- `--help` — print help for the top-level command, or for one subcommand (`notes add --help`).

Subcommands:

- `add TITLE [--body TEXT]` — save a note. `TITLE` is required and must contain a non-blank character. `--body` is optional plain text and defaults to empty.
- `list [--json]` — list notes in ascending ID order. Without `--json`, the table shows ID and title. With `--json`, each record includes `id`, `title`, `body`, and `created_at`.
- `search KEYWORD [--json]` — case-insensitive literal substring match against titles and bodies. `KEYWORD` must not be blank.
- `show NOTE_ID [--json]` — print one note. `NOTE_ID` is an integer from 1 through 2^63-1.
- `delete NOTE_ID` — delete that note. Remaining IDs stay the same. SQLite may reuse the highest deleted ID for a later `add`. Deleting the last note leaves the database file in place.

A value that starts with `-` is an option unless you end option parsing first: `notes add -- -n`.

## Storage

The default file is `notes.db` in Click's platform-specific user app-data
directory for `note-taking-app`, independent of the current working directory:

- Linux: `$XDG_CONFIG_HOME/note-taking-app/notes.db`, or `~/.config/note-taking-app/notes.db`.
- macOS: `~/Library/Application Support/note-taking-app/notes.db`.
- Windows: `%LOCALAPPDATA%\note-taking-app\notes.db`.

Choose a different database with the global option before the command, or set
`NOTES_DATABASE`:

```bash
notes --database ./my-notes.db add "Local collection" --body "Saved here."
notes --database ./my-notes.db list --json
```

An explicit relative path is relative to the working directory. Different paths
select separate collections. Read commands and `delete` do not create a missing
database. The first successful write creates its parent directories and SQLite
database.
On POSIX, newly created database files use mode `0600`; OS permissions still
control access, particularly on Windows. Use a trusted, private local directory.

Existing files must be databases created by this version with the recognized
schema. Foreign, empty, corrupt, unsupported-version, symlink, and non-regular
files are rejected instead of overwritten. There is no automatic migration or
repair. If this process creates a new database file and the first commit does
not succeed, that empty file is removed so the same path can be retried.
Existing files are not removed by that cleanup. Do not delete an existing
database that might contain notes. A title, body, or timestamp that is not text
(for example a BLOB written by another program) makes `list`, `search`, and
`show` fail with an error that includes the note ID; `delete` can remove it.
For backups, stop writers and copy the database and any SQLite journal files
together, or use SQLite's backup tools.

SQLite serializes writes and waits up to two seconds for a lock before reporting
an error. This is a local, single-user application, not a multi-user service.
Concurrent first-time creation may require retrying after the first writer
finishes. File-type checks are defensive checks, not a guarantee against another
process replacing paths concurrently. No network-filesystem guarantees are made.

## Development

```bash
python -m pip install ".[dev]"
python -m ruff check .
python -m pytest -q
python -m build
python scripts/wheel_smoke.py
```

Tests use temporary files, check persistence in fresh processes, preserve invalid
and foreign databases, and exercise lock, insert, delete, and commit failures.
CI runs Ruff and pytest, then builds a wheel and tests the installed `notes`
console command outside the source directory. Its configured matrix covers Linux
Python 3.8/3.12/3.14 and Windows/macOS Python 3.12.

## License

MIT License.
