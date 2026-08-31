"""Guardrails for alembic migrations.

A recurring mistake is copy-pasting a placeholder revision id (e.g. ``a1b2c3d4e5f6``)
that already exists, which produces duplicate revisions and multiple/zero heads —
the bot fails to start and CI breaks. These tests catch it locally before pushing.
"""

import re
import runpy
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
