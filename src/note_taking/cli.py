"""CLI interface."""
import click
from rich.console import Console
from rich.table import Table

console = Console()

@click.group()
@click.version_option(version="0.1.0")
def main():
    """Note Taking App - Manage your notes from the terminal."""
    pass

@main.command()
@click.argument("title")
def add(title):
    """Add a new note."""
    console.print(f"✅ Added note: [bold green]{title}[/bold green]")

@main.command()
def list():
    """List all notes."""
    table = Table(title="Notes")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Tags")
    table.add_row("1", "Meeting Notes", "work, important")
    console.print(table)

@main.command()
@click.argument("keyword")
def search(keyword):
    """Search notes."""
    console.print(f"🔍 Searching for: {keyword}")

if __name__ == "__main__":
    main()
