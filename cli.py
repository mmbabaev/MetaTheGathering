import os

os.environ.setdefault("BOT_ENV", "debug")
os.environ["DEBUG"] = "false"  # suppress SQLAlchemy echo in CLI

import typer

from cli.achievements import app as achievements_app
from cli.magicoculus import app as magicoculus_app
from cli.migration import app as migration_app
from cli.tournament import app as tournament_app
from cli.user import app as user_app

app = typer.Typer(no_args_is_help=True, help="MetaGatherer debug CLI")
app.add_typer(tournament_app, name="tournament", help="Управление турнирами")
app.add_typer(user_app, name="user", help="Управление пользователями")
app.add_typer(achievements_app, name="achievements", help="Ачивки: пересчёт и просмотр")
app.add_typer(magicoculus_app, name="magicoculus", help="Подготовка импорта турниров в Magic Oculus")
app.add_typer(migration_app, name="migration", help="Сбор исторических турниров для Magic Oculus")

if __name__ == "__main__":
    app()
