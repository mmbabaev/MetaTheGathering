import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "266ab09f6f31_move_pair_of_dice_schedule.py"


def _migration():
    spec = importlib.util.spec_from_file_location("pair_of_dice_schedule_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _old_table(metadata):
    return sa.Table(
        "club_schedules",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("club_name", sa.String(64), nullable=False),
        sa.Column("weekday", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("create_time", sa.String(5), nullable=False),
        sa.Column("game_time", sa.String(5), nullable=False),
        sa.Column("reminder_time", sa.String(5)),
        sa.Column("import_times", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("club_name", "weekday"),
    )


def test_upgrade_moves_both_events_and_adds_creation_offset(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    old_schedule = _old_table(metadata)
    metadata.create_all(engine)
    now = datetime(2026, 8, 14)

    with engine.begin() as connection:
        connection.execute(
            sa.insert(old_schedule),
            [
                {
                    "club_name": "Pair of dice",
                    "weekday": weekday,
                    "enabled": True,
                    "create_time": "12:00",
                    "game_time": "19:30",
                    "reminder_time": "19:25",
                    "import_times": migration.TUESDAY_IMPORT_TIMES,
                    "created_at": now,
                    "updated_at": now,
                }
                for weekday in ("monday", "wednesday")
            ],
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        upgraded = sa.Table("club_schedules", sa.MetaData(), autoload_with=connection)
        rows = (
            connection.execute(
                sa.select(upgraded).where(upgraded.c.club_name == "Pair of dice").order_by(upgraded.c.weekday)
            )
            .mappings()
            .all()
        )

    assert [row["weekday"] for row in rows] == ["sunday", "tuesday"]
    sunday, tuesday = rows
    assert sunday["create_time"] == "18:30"
    assert sunday["create_days_before"] == 1
    assert sunday["game_time"] == "13:30"
    assert sunday["reminder_time"] == "13:25"
    assert sunday["import_times"] == migration.SUNDAY_IMPORT_TIMES
    assert tuesday["create_time"] == "18:30"
    assert tuesday["create_days_before"] == 1
    assert tuesday["game_time"] == "19:30"
    assert tuesday["reminder_time"] == "19:25"
    assert tuesday["import_times"] == migration.TUESDAY_IMPORT_TIMES


def test_non_pair_rows_keep_same_schedule_with_zero_offset(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    old_schedule = _old_table(metadata)
    metadata.create_all(engine)
    now = datetime(2026, 8, 14)

    with engine.begin() as connection:
        connection.execute(
            sa.insert(old_schedule),
            {
                "club_name": "Goldfish",
                "weekday": "friday",
                "enabled": True,
                "create_time": "12:00",
                "game_time": "19:45",
                "reminder_time": "19:45",
                "import_times": migration.TUESDAY_IMPORT_TIMES,
                "created_at": now,
                "updated_at": now,
            },
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        upgraded = sa.Table("club_schedules", sa.MetaData(), autoload_with=connection)
        row = (
            connection.execute(sa.select(upgraded).where(upgraded.c.club_name == "Goldfish"))
            .mappings()
            .one()
        )

    assert row["club_name"] == "Goldfish"
    assert row["weekday"] == "friday"
    assert row["create_time"] == "12:00"
    assert row["create_days_before"] == 0
    assert row["game_time"] == "19:45"
