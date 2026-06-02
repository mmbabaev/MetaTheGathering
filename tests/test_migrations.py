"""Guardrails for alembic migrations.

A recurring mistake is copy-pasting a placeholder revision id (e.g. ``a1b2c3d4e5f6``)
that already exists, which produces duplicate revisions and multiple/zero heads —
the bot fails to start and CI breaks. These tests catch it locally before pushing.
"""

import re
from pathlib import Path

from alembic.config import Config
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
