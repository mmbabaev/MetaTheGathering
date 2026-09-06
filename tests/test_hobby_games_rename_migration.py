import runpy
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "7167a65fad51_rename_hobby_games_kaliningrad.py"
OLD_NAME = "Hobby Games"
NEW_NAME = "Hobby Games - Калининград"


def _tables(metadata: sa.MetaData) -> dict[str, tuple[sa.Table, str]]:
    return {
        "tournaments": (
            sa.Table(
                "tournaments",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("club", sa.String(64)),
            ),
            "club",
        ),
        "club_schedules": (
            sa.Table(
                "club_schedules",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("club_name", sa.String(64), nullable=False),
            ),
            "club_name",
        ),
        "club_settings": (
            sa.Table(
                "club_settings",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("club_name", sa.String(64), nullable=False),
            ),
            "club_name",
        ),
        "tournament_creation_plans": (
            sa.Table(
                "tournament_creation_plans",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("club_name", sa.String(64), nullable=False),
            ),
            "club_name",
        ),
        "club_announcement_settings": (
            sa.Table(
                "club_announcement_settings",
                metadata,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("club_name", sa.String(64), nullable=False),
            ),
            "club_name",
        ),
    }


def test_upgrade_and_downgrade_rename_all_persisted_club_references():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    tables = _tables(metadata)
    metadata.create_all(engine)
    migration = runpy.run_path(str(MIGRATION_PATH))

    with engine.begin() as connection:
        for table, column_name in tables.values():
            connection.execute(table.insert().values(id=1, **{column_name: OLD_NAME}))
            connection.execute(table.insert().values(id=2, **{column_name: "Goldfish"}))

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        for table, column_name in tables.values():
            values = connection.execute(sa.select(getattr(table.c, column_name)).order_by(table.c.id)).scalars().all()
            assert values == [NEW_NAME, "Goldfish"]

        with Operations.context(context):
            migration["downgrade"]()

        for table, column_name in tables.values():
            values = connection.execute(sa.select(getattr(table.c, column_name)).order_by(table.c.id)).scalars().all()
            assert values == [OLD_NAME, "Goldfish"]
