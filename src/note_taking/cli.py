"""Command-line interface for persisted local notes."""

import json
from pathlib import Path

import click
from rich.cells import cell_len
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__, storage


def _text(value, name, required=False):
    if "\x00" in value or (required and not value.strip()):
        raise click.BadParameter("must be nonblank and contain no NUL characters" if required
                                 else "must contain no NUL characters", param_hint=name)
    return value


def _call(function, *args):
    try:
        return function(*args)
    except storage.StorageError as exc:
        raise click.ClickException(str(exc)) from exc


def _display_width(value):
    lines = str(value).splitlines() or [""]
    return max(cell_len(line) for line in lines)


def _display(rows, as_json, empty_message):
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
    elif not rows:
        click.echo(empty_message)
    else:
        table = Table(title="Notes")
        table.add_column("ID", style="cyan", overflow="fold")
        table.add_column("Title", style="green", overflow="fold")
        for row in rows:
            table.add_row(str(row["id"]), Text(row["title"]))
        console = Console()
        # Rich ellipsizes a title that is wider than the console. On a dumb
        # terminal, width is ignored unless height is set as well.
        needed = (
            max(_display_width("ID"), max(_display_width(row["id"]) for row in rows))
            + max(_display_width("Title"), max(_display_width(row["title"]) for row in rows))
            + 9
        )
        if needed > console.width:
            console = Console(width=needed, height=max(console.height, 1000))
        console.print(table)


@click.group()
@click.version_option(version=__version__)
@click.option("--database", envvar="NOTES_DATABASE", type=click.Path(),
              help="SQLite file. Default: notes.db in your user app-data directory.")
@click.pass_context
def main(ctx, database):
    """Save, list, read, search, and delete local notes."""
    if database is None:
        database = str(Path(click.get_app_dir("note-taking-app", roaming=False)) / "notes.db")
    try:
        ctx.obj = storage.database_path(database)
    except (OSError, ValueError, RuntimeError) as exc:
        raise click.ClickException("Invalid database path: %s" % exc) from exc


@main.command()
@click.argument("title")
@click.option("--body", default="", help="Note body, stored as plain text (including Markdown).")
@click.pass_obj
def add(database, title, body):
    """Save a new note. Print its ID only after the transaction commits."""
    _text(title, "TITLE", required=True)
    _text(body, "--body")
    note_id = _call(storage.add_note, database, title, body)
    click.echo("Added note #%d: %s" % (note_id, title))


@main.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Output complete records as JSON.")
@click.pass_obj
def list_command(database, as_json):
    """List stored notes in ID order."""
    _display(_call(storage.list_notes, database), as_json, "No notes yet.")


@main.command()
@click.argument("keyword")
@click.option("--json", "as_json", is_flag=True, help="Output complete matching records as JSON.")
@click.pass_obj
def search(database, keyword, as_json):
    """Find a literal, case-insensitive substring in titles or bodies."""
    _text(keyword, "KEYWORD", required=True)
    _display(_call(storage.list_notes, database, keyword), as_json, "No matching notes.")


@main.command()
@click.argument("note_id", type=click.IntRange(1, 9223372036854775807))
@click.option("--json", "as_json", is_flag=True, help="Output the complete record as JSON.")
@click.pass_obj
def show(database, note_id, as_json):
    """Read the full title and body of one note."""
    row = _call(storage.get_note, database, note_id)
    if row is None:
        raise click.ClickException("Note #%d does not exist." % note_id)
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False))
    else:
        click.echo("#%d: %s" % (row["id"], row["title"]))
        click.echo(row["body"])


@main.command()
@click.argument("note_id", type=click.IntRange(1, 9223372036854775807))
@click.pass_obj
def delete(database, note_id):
    """Delete one note by ID. Other notes keep their IDs."""
    _call(storage.delete_note, database, note_id)
    click.echo("Deleted note #%d." % note_id)


if __name__ == "__main__":
    main()
