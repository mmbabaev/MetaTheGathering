"""Guardrails for alembic migrations.

A recurring mistake is copy-pasting a placeholder revision id (e.g. ``a1b2c3d4e5f6``)
that already exists, which produces duplicate revisions and multiple/zero heads —
the bot fails to start and CI breaks. These tests catch it locally before pushing.
"""

import re
import runpy
from datetime import datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parent.parent
VERSIONS_DIR = ROOT / "alembic" / "versions"

_REVISION_RE = re.compile(r"""^revision(?::\s*[^=]+)?\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)


def _revision_ids() -> list[str]:
    ids: list[str] = []
    for path in VERSIONS_DIR.glob("*.py"):
        m = _REVISION_RE.search(path.read_text(encoding="utf-8"))
        assert m, f"Could not find a `revision = ...` line in {path.name}"
        ids.append(m.group(1))
    return ids


def test_revision_ids_are_unique():
    ids = _revision_ids()
    duplicates = sorted({rev for rev in ids if ids.count(rev) > 1})
    assert not duplicates, (
        f"Duplicate alembic revision id(s): {duplicates}. "
        f'Generate a fresh id with `python3 -c "import uuid; print(uuid.uuid4().hex[:12])"`.'
    )


def test_single_alembic_head():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 alembic head, got {len(heads)}: {heads}"


def test_swiss_decklist_migration_keeps_existing_tournaments_out_of_reminders():
    metadata = sa.MetaData()
    tournaments = sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("participants", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "tournament_creation_plans",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer),
        sa.Column("created_by_tg_id", sa.BigInteger, nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "e2c203099387_add_swiss_decklists.py"))

    with engine.begin() as connection:
        connection.execute(tournaments.insert().values(id=1))
        plans = metadata.tables["tournament_creation_plans"]
        connection.execute(plans.insert().values(id=1, tournament_id=1, created_by_tg_id=42))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        migrated = sa.Table("tournaments", sa.MetaData(), autoload_with=connection)
        row = connection.execute(
            sa.select(
                migrated.c.created_by_tg_id,
                migrated.c.decklist_reminders_enabled,
            )
        ).one()

    assert row == (42, False)


def test_endstep_leaderboard_snapshot_migration_creates_cache_table():
    engine = sa.create_engine("sqlite://")
    migration = runpy.run_path(str(VERSIONS_DIR / "e2c9d12d05ed_add_endstep_ru_leaderboard_snapshots.py"))

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        table = sa.Table("endstep_ru_leaderboard_snapshots", sa.MetaData(), autoload_with=connection)
        assert {
            "generated_at",
            "candidate_count",
            "rows_json",
            "missing_usernames_json",
            "ambiguous_usernames_json",
        } <= set(table.c.keys())

        with Operations.context(context):
            migration["downgrade"]()
        assert not sa.inspect(connection).has_table("endstep_ru_leaderboard_snapshots")


def test_round_pairings_message_tracking_migration_creates_table():
    metadata = sa.MetaData()
    sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "330c09696d85_track_round_pairings_messages.py"))

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        table = sa.Table("tournament_round_pairings_messages", sa.MetaData(), autoload_with=connection)
        assert {"tournament_id", "round_number", "chat_id", "message_id"} <= set(table.c.keys())

        with Operations.context(context):
            migration["downgrade"]()
        assert not sa.inspect(connection).has_table("tournament_round_pairings_messages")


def test_tournament_online_marker_backfills_existing_rows_as_offline():
    metadata = sa.MetaData()
    tournaments = sa.Table(
        "tournaments",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "00840004f838_add_tournament_is_online.py"))

    with engine.begin() as connection:
        connection.execute(tournaments.insert().values(id=1))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        migrated = sa.Table("tournaments", sa.MetaData(), autoload_with=connection)
        connection.execute(migrated.insert().values(id=2))
        rows = connection.execute(sa.select(migrated.c.id, migrated.c.is_online).order_by(migrated.c.id)).all()

    assert rows == [(1, False), (2, False)]


def test_tournament_creation_plan_migration_defaults_to_pending():
    metadata = sa.MetaData()
    sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "4953faa801dd_add_tournament_creation_plans.py"))

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        plans = sa.Table("tournament_creation_plans", sa.MetaData(), autoload_with=connection)
        now = datetime(2026, 9, 4)
        connection.execute(
            plans.insert().values(
                id=1,
                club_name="Endstep-ru",
                created_by_tg_id=1,
                announce_at=now,
                event_at=now + timedelta(days=1),
                created_at=now,
                updated_at=now,
            )
        )
        assert connection.execute(sa.select(plans.c.status)).scalar_one() == "pending"


def test_club_announcement_settings_migration_defaults_to_none():
    metadata = sa.MetaData()
    sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    plan_migration = runpy.run_path(str(VERSIONS_DIR / "4953faa801dd_add_tournament_creation_plans.py"))
    settings_migration = runpy.run_path(str(VERSIONS_DIR / "11cdd73fac96_add_club_announcement_settings.py"))

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            plan_migration["upgrade"]()
            settings_migration["upgrade"]()
        settings_table = sa.Table("club_announcement_settings", sa.MetaData(), autoload_with=connection)
        now = datetime(2026, 9, 4)
        connection.execute(settings_table.insert().values(id=1, club_name="Endstep-ru", created_at=now, updated_at=now))
        plans = sa.Table("tournament_creation_plans", sa.MetaData(), autoload_with=connection)
        connection.execute(
            plans.insert().values(
                id=1,
                club_name="Endstep-ru",
                created_by_tg_id=1,
                announce_at=now,
                event_at=now + timedelta(days=1),
                created_at=now,
                updated_at=now,
            )
        )

        assert connection.execute(sa.select(settings_table.c.destination)).scalar_one() == "none"
        assert connection.execute(sa.select(plans.c.announcement_chat_label)).scalar_one() == "не отправлять"


def test_online_round_results_migration_defaults_to_participant_view():
    metadata = sa.MetaData()
    tournaments = sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "71797c25e8da_add_online_round_results.py"))

    with engine.begin() as connection:
        connection.execute(tournaments.insert().values(id=1))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        migrated = sa.Table("tournaments", sa.MetaData(), autoload_with=connection)
        matches = sa.Table("round_matches", sa.MetaData(), autoload_with=connection)
        now = datetime(2026, 9, 4)
        connection.execute(
            matches.insert().values(
                id=1,
                tournament_id=1,
                round_number=1,
                pairing_key="dummy-not-a-real-pairing-key",
                player1_name="Игрок 1",
                player2_name="Игрок 2",
                created_at=now,
                updated_at=now,
            )
        )
        assert connection.execute(sa.select(migrated.c.show_round_pairings)).scalar_one() is False
        assert connection.execute(sa.select(matches.c.status, matches.c.revision)).one() == ("unreported", 0)


def test_konetskhod_rename_migration_numbers_active_tournament():
    metadata = sa.MetaData()
    tournaments = sa.Table(
        "tournaments",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("club", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    registration_messages = sa.Table(
        "tournament_registration_messages",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, nullable=False),
        sa.Column("base_text", sa.String),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "b516420f583a_rename_endstep_ru_to_konetskhod.py"))

    now = datetime(2026, 9, 19)
    base_text = "🎮 ⏭️🦶 Endstep-ru Pauper — 26.09.2026 в 19:00\nТурнир создан. Регистрация открыта."
    with engine.begin() as connection:
        connection.execute(
            tournaments.insert().values(
                [
                    {
                        "id": 1,
                        "title": "⏭️🦶 Endstep-ru Pauper 22.08.2026",
                        "chat_id": 0,
                        "club": "Endstep-ru",
                        "status": "CLOSED",
                        "created_at": now,
                    },
                    {
                        "id": 2,
                        "title": "⏭️🦶 Endstep-ru Pauper 29.08.2026",
                        "chat_id": 0,
                        "club": None,
                        "status": "CLOSED",
                        "created_at": now,
                    },
                    {
                        "id": 3,
                        "title": "⏭️🦶 Endstep-ru Pauper 26.09.2026",
                        "chat_id": -100,
                        "club": "Endstep-ru",
                        "status": "REGISTRATION",
                        "created_at": now,
                    },
                    {
                        "id": 4,
                        "title": "⏭️🦶 Endstep draft 20.09.2026",
                        "chat_id": -200,
                        "club": "Endstep draft",
                        "status": "REGISTRATION",
                        "created_at": now,
                    },
                ]
            )
        )
        connection.execute(
            registration_messages.insert().values(
                [
                    {"id": 1, "tournament_id": 3, "base_text": base_text},
                    {"id": 2, "tournament_id": 4, "base_text": base_text},
                ]
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        titles = dict(connection.execute(sa.select(tournaments.c.id, tournaments.c.title)).all())
        assert titles[1] == "⏭️🦶 Endstep-ru Pauper 22.08.2026"  # закрытые не трогаем
        assert titles[2] == "⏭️🦶 Endstep-ru Pauper 29.08.2026"
        assert titles[3] == "⏭️🦶 Концеход Pauper #3"
        assert titles[4] == "⏭️🦶 Endstep draft 20.09.2026"  # draft не Концеход

        texts = dict(
            connection.execute(
                sa.select(registration_messages.c.tournament_id, registration_messages.c.base_text)
            ).all()
        )
        assert "⏭️🦶 Концеход Pauper #3 — 26.09.2026" in texts[3]
        assert texts[4] == base_text  # чужие сообщения не трогаем


def test_endstep_username_and_club_settings_migration_defaults_safe():
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tg_id", sa.BigInteger, nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "462d69c18f40_add_endstep_username_and_club_settings.py"))

    with engine.begin() as connection:
        connection.execute(users.insert().values(id=1, tg_id=100))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        migrated_users = sa.Table("users", sa.MetaData(), autoload_with=connection)
        club_settings = sa.Table("club_settings", sa.MetaData(), autoload_with=connection)
        assert connection.execute(sa.select(migrated_users.c.endstep_username)).scalar_one() is None
        connection.execute(
            club_settings.insert().values(
                id=1,
                club_name="Endstep-ru",
                created_at=datetime(2026, 9, 4),
                updated_at=datetime(2026, 9, 4),
            )
        )
        assert connection.execute(sa.select(club_settings.c.publish_pairings)).scalar_one() is False


def test_user_city_migration_keeps_existing_city_empty_and_accepts_custom_value():
    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tg_id", sa.BigInteger, nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "572aa2e07c0c_add_user_city.py"))

    with engine.begin() as connection:
        connection.execute(users.insert().values(id=1, tg_id=100))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        migrated_users = sa.Table("users", sa.MetaData(), autoload_with=connection)
        assert connection.execute(sa.select(migrated_users.c.city)).scalar_one() is None
        connection.execute(migrated_users.update().values(city="Казань"))
        assert connection.execute(sa.select(migrated_users.c.city)).scalar_one() == "Казань"


def test_creation_plan_custom_title_migration_adds_nullable_column():
    metadata = sa.MetaData()
    sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    plans_migration = runpy.run_path(str(VERSIONS_DIR / "4953faa801dd_add_tournament_creation_plans.py"))
    custom_migration = runpy.run_path(str(VERSIONS_DIR / "842c718201a6_add_custom_title_to_creation_plans.py"))

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            plans_migration["upgrade"]()
            custom_migration["upgrade"]()
        plans = sa.Table("tournament_creation_plans", sa.MetaData(), autoload_with=connection)
        assert {"custom_title"} <= set(plans.c.keys())

        with Operations.context(context):
            custom_migration["downgrade"]()
        plans = sa.Table("tournament_creation_plans", sa.MetaData(), autoload_with=connection)
        assert "custom_title" not in plans.c.keys()


def test_internal_swiss_migration_keeps_existing_tournaments_on_aetherhub():
    metadata = sa.MetaData()
    tournaments = sa.Table("tournaments", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    participants = sa.Table(
        "participants",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
    )
    pairings = sa.Table(
        "round_pairings",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tournament_id", sa.Integer, nullable=False),
        sa.Column("round_number", sa.Integer, nullable=False),
        sa.Column("player_name", sa.String(255), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    migration = runpy.run_path(str(VERSIONS_DIR / "8d10f8278807_add_internal_swiss_mode.py"))

    with engine.begin() as connection:
        connection.execute(tournaments.insert().values(id=1))
        connection.execute(participants.insert().values(id=1, tournament_id=1, user_id=1))
        connection.execute(pairings.insert().values(id=1, tournament_id=1, round_number=1, player_name="Игрок"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

        migrated_tournaments = sa.Table("tournaments", sa.MetaData(), autoload_with=connection)
        migrated_participants = sa.Table("participants", sa.MetaData(), autoload_with=connection)
        migrated_pairings = sa.Table("round_pairings", sa.MetaData(), autoload_with=connection)
        assert connection.execute(sa.select(migrated_tournaments.c.engine_mode)).scalar_one() == "aetherhub"
        assert connection.execute(sa.select(migrated_tournaments.c.swiss_rounds)).scalar_one() is None
        assert connection.execute(sa.select(migrated_participants.c.swiss_initial_rank)).scalar_one() is None
        assert connection.execute(sa.select(migrated_pairings.c.player_user_id)).scalar_one() is None


def test_split_spy_general_names_repairs_only_classification_cache():
    metadata = sa.MetaData()
    archetypes = sa.Table(
        "archetypes",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("general_name", sa.String(255)),
        sa.Column("macro_name", sa.String(255)),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    rows = [
        {"id": 1, "name": "Spy", "general_name": "Spy Walls", "macro_name": "Spy"},
        {"id": 2, "name": "Spy Combo", "general_name": "Spy Walls", "macro_name": "Spy"},
        {"id": 3, "name": "Spy Walls", "general_name": "Spy Walls", "macro_name": "Spy"},
        {"id": 4, "name": "Walls combo", "general_name": "Spy Walls", "macro_name": "Walls"},
        {"id": 5, "name": "Blue Terror", "general_name": "Blue Terror", "macro_name": "Terror"},
    ]
    migration = runpy.run_path(str(VERSIONS_DIR / "a62db8f5ffdd_split_spy_and_spy_walls_general_names.py"))

    with engine.begin() as connection:
        connection.execute(archetypes.insert(), rows)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
        actual = connection.execute(
            sa.select(
                archetypes.c.id,
                archetypes.c.name,
                archetypes.c.general_name,
                archetypes.c.macro_name,
            ).order_by(archetypes.c.id)
        ).all()

    assert actual == [
        (1, "Spy", "Spy", "Spy"),
        (2, "Spy Combo", "Spy", "Spy"),
        (3, "Spy Walls", "Spy Walls", "Spy"),
        (4, "Walls combo", "Walls Combo", "Walls"),
        (5, "Blue Terror", "Blue Terror", "Terror"),
    ]
