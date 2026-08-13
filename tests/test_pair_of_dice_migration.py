import importlib.util
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "d05d9619e6af_add_pair_of_dice_schedules.py"


def _migration():
    spec = importlib.util.spec_from_file_location("pair_of_dice_migration", MIGRATION_PATH)
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
        sa.Column("game_time", sa.String(5), nullable=False),
        sa.Column("reminder_time", sa.String(5)),
        sa.Column("import_times", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("club_name", "weekday"),
    )


def test_migration_seeds_full_schedule_on_empty_database(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    schedules = _table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        rows = connection.execute(
            sa.select(schedules.c.club_name, schedules.c.weekday).order_by(
                schedules.c.club_name,
                schedules.c.weekday,
            )
        ).all()

    assert rows == [
        ("Edinorog", "monday"),
        ("Edinorog", "thursday"),
        ("Goldfish", "friday"),
        ("Pair of dice", "monday"),
        ("Pair of dice", "wednesday"),
    ]


def test_migration_copies_current_edinorog_monday_schedule(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    schedules = _table(metadata)
    metadata.create_all(engine)
    now = datetime(2026, 8, 14)

    with engine.begin() as connection:
        connection.execute(
            sa.insert(schedules),
            [
                {
                    "club_name": "Edinorog",
                    "weekday": "monday",
                    "enabled": False,
                    "create_time": "13:15",
                    "game_time": "20:10",
                    "reminder_time": None,
                    "import_times": "20:30,00:15",
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        pair_rows = (
            connection.execute(
                sa.select(schedules).where(schedules.c.club_name == "Pair of dice").order_by(schedules.c.weekday)
            )
            .mappings()
            .all()
        )

    assert [row["weekday"] for row in pair_rows] == ["monday", "wednesday"]
    assert all(row["enabled"] for row in pair_rows)
    assert all(row["create_time"] == "13:15" for row in pair_rows)
    assert all(row["game_time"] == "20:10" for row in pair_rows)
    assert all(row["reminder_time"] is None for row in pair_rows)
    assert all(row["import_times"] == "20:30,00:15" for row in pair_rows)

    with engine.begin() as connection:
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.downgrade()
        remaining = connection.execute(sa.select(schedules.c.club_name)).scalars().all()

    assert remaining == ["Edinorog"]
