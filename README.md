# Note Taking App

A small, local SQLite note CLI for Python 3.8+. Create notes, read them later,
and find literal text in their titles or bodies. No account or server is needed.

## Status

Version 0.2.0 replaces the original prototype's simulated success messages and
fixed example list with real persistence. The original 0.1.0 `add` command did
not store notes, so there is no saved 0.1.0 database to migrate or recover.

Supported features:

- Save a title and optional plain-text body, with a stable ID and UTC creation time.
- List and read saved notes across separate invocations and working directories.
- Search titles and bodies using Unicode-aware, case-insensitive literal substrings.
- Read complete records as JSON.

Markdown is stored as text, not rendered. Tags, folders, pinning, editing,
deleting, import/export, PDF/HTML conversion, and indexed full-text search are
not implemented. Search scans the stored notes and is intended for small local
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
```

An `add` command reports success only after SQLite commits the note. Unknown
IDs, invalid input, unreadable/locked databases, and save failures return a
nonzero exit code. A search with no matches returns an empty result, not an error.
Titles and search terms must not be blank. NUL characters are not accepted.

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
select separate collections. Read commands do not create a missing database.
The first successful write creates its parent directories and SQLite database.
On POSIX, newly created database files use mode `0600`; OS permissions still
control access, particularly on Windows. Use a trusted, private local directory.

Existing files must be databases created by this version with the recognized
schema. Foreign, empty, corrupt, unsupported-version, symlink, and non-regular
files are rejected instead of overwritten. There is no automatic migration or
repair. If initial creation fails, an empty file may remain; retry with a fresh
path after resolving the error. Do not delete an existing database that might
contain notes. For backups, stop writers and copy the database and any SQLite
journal files together, or use SQLite's backup tools.

SQLite serializes writes and waits up to two seconds for a lock before reporting
an error. This is a local, single-user application, not a multi-user service.
Concurrent first-time creation may require retrying after the first writer
finishes. File-type checks are defensive checks, not a guarantee against another
process replacing paths concurrently. No network-filesystem guarantees are made.

## Development

```bash
python -m pip install ".[dev]"
python -m pytest -q
python -m build
python scripts/wheel_smoke.py
```

Tests use temporary files, check persistence in fresh processes, preserve invalid
and foreign databases, and exercise lock, insert, and commit failures. CI also
builds a wheel and tests the installed `notes` console command outside the source
directory. Its configured matrix covers Linux Python 3.8/3.12/3.14 and
Windows/macOS Python 3.12.

## License

MIT License.
