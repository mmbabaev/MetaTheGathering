import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = ROOT / "alembic" / "versions" / "3c1587c33ad2_enable_hobby_games_imports.py"


def _migration():
    spec = importlib.util.spec_from_file_location("hobby_games_imports_migration", MIGRATION_PATH)
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
        sa.Column("import_times", sa.String(512), nullable=False),
    )


def test_upgrade_enables_hobby_games_imports_and_downgrade_reverts(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    schedules = _table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            sa.insert(schedules),
            {"club_name": "Hobby Games", "weekday": "saturday", "import_times": ""},
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

        migration.upgrade()
        assert connection.execute(sa.select(schedules.c.import_times)).scalar_one() == migration.IMPORT_TIMES

        migration.downgrade()
        assert connection.execute(sa.select(schedules.c.import_times)).scalar_one() == ""


def test_upgrade_preserves_admin_custom_import_schedule(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    schedules = _table(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            sa.insert(schedules),
            {"club_name": "Hobby Games", "weekday": "saturday", "import_times": "18:15,19:15"},
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

        migration.upgrade()

        assert connection.execute(sa.select(schedules.c.import_times)).scalar_one() == "18:15,19:15"
