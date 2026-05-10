import os

os.environ.setdefault("BOT_ENV", "debug")
os.environ["DEBUG"] = "false"  # suppress SQLAlchemy echo in CLI

import typer

from cli.tournament import app as tournament_app
from cli.user import app as user_app

app = typer.Typer(no_args_is_help=True, help="MetaGatherer debug CLI")
app.add_typer(tournament_app, name="tournament", help="Управление турнирами")
app.add_typer(user_app, name="user", help="Управление пользователями")

if __name__ == "__main__":
    app()
