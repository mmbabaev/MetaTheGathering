"""stub for missing revision

Revision ID: 1413b684d806
Revises: 1292fad8bfd5
Create Date: 2026-04-14 00:00:00.000000

This file is a stub for a migration that was applied to the database
but whose file was lost. The schema changes it introduced are already
present in the database; this file exists only so Alembic can resolve
the revision chain.
"""
from typing import Sequence, Union

revision: str = '1413b684d806'
down_revision: Union[str, Sequence[str], None] = '1292fad8bfd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
