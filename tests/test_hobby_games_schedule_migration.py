import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "b4b96e826905_add_hobby_games_schedule.py"


def _migration():
    spec = importlib.util.spec_from_file_location("hobby_games_schedule_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table(metadata):
    return sa.Table(
        "club_schedules",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("club_name", sa.String(64), nullable=False),
        sa.Column("weekday", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("create_time", sa.String(5), nullable=False),
        sa.Column("create_days_before", sa.Integer, nullable=False),
        sa.Column("game_time", sa.String(5), nullable=False),
        sa.Column("reminder_time", sa.String(5)),
        sa.Column("import_times", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("club_name", "weekday"),
    )


def test_upgrade_adds_hobby_games_without_changing_existing_rows(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    schedules = _table(metadata)
    metadata.create_all(engine)
    now = datetime(2026, 8, 17)

    with engine.begin() as connection:
        connection.execute(
            sa.insert(schedules),
            {
                "club_name": "Goldfish",
                "weekday": "friday",
                "enabled": False,
                "create_time": "13:00",
                "create_days_before": 0,
                "game_time": "19:45",
                "reminder_time": None,
                "import_times": "",
                "created_at": now,
                "updated_at": now,
            },
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        rows = connection.execute(sa.select(schedules).order_by(schedules.c.club_name)).mappings().all()

    assert len(rows) == 2
    goldfish, hobby_games = rows
    assert goldfish["club_name"] == "Goldfish"
    assert goldfish["enabled"] is False
    assert goldfish["create_time"] == "13:00"
    assert hobby_games["club_name"] == "Hobby Games"
    assert hobby_games["weekday"] == "saturday"
    assert hobby_games["enabled"] is True
    assert hobby_games["create_time"] == "18:30"
    assert hobby_games["create_days_before"] == 1
    assert hobby_games["game_time"] == "17:00"
    assert hobby_games["reminder_time"] == "16:55"
    assert hobby_games["import_times"] == ""


def test_upgrade_is_idempotent_and_downgrade_only_removes_hobby_games(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    schedules = _table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert connection.execute(sa.select(sa.func.count()).select_from(schedules)).scalar_one() == 1

        migration.downgrade()
        assert connection.execute(sa.select(sa.func.count()).select_from(schedules)).scalar_one() == 0
