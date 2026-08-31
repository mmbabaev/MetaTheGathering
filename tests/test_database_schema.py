from types import SimpleNamespace

import pytest

from core.config import settings
from core.database import database_connect_args


def test_database_schema_sets_postgres_search_path(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_SCHEMA", "metagatherer_pr_271")
    monkeypatch.setattr(settings, "DATABASE_URL", SimpleNamespace(scheme="postgresql+psycopg2"))

    assert database_connect_args() == {"options": "-csearch_path=metagatherer_pr_271"}


@pytest.mark.parametrize("schema", ["PR_271", "public,evil", "bad-name", "271"])
def test_database_schema_rejects_unsafe_identifiers(monkeypatch, schema):
    monkeypatch.setattr(settings, "DATABASE_SCHEMA", schema)

    with pytest.raises(ValueError, match="lowercase PostgreSQL identifier"):
        database_connect_args()


def test_database_schema_rejects_non_postgres_database(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_SCHEMA", "metagatherer_pr_271")
    monkeypatch.setattr(settings, "DATABASE_URL", SimpleNamespace(scheme="sqlite"))

    with pytest.raises(ValueError, match="supported only for PostgreSQL"):
        database_connect_args()
