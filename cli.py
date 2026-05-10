import os

os.environ.setdefault("BOT_ENV", "debug")
os.environ["DEBUG"] = "false"  # suppress SQLAlchemy echo in CLI

import typer

from cli.tournament import app as tournament_app

app = typer.Typer(no_args_is_help=True, help="MetaGatherer debug CLI")
app.add_typer(tournament_app, name="tournament", help="Управление турнирами")

if __name__ == "__main__":
    app()
