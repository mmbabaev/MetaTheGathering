"""Add single-elimination playoff to internal Swiss tournaments.

Large online Swiss events can play a top-8/top-16 cut after the Swiss rounds.
The tournament stores the planned cut size and each cut player keeps their
bracket seed.
"""

from alembic import op
import sqlalchemy as sa

revision = "337216afe8c3"
down_revision = "842c718201a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("playoff_size", sa.Integer(), nullable=True))
    op.add_column("participants", sa.Column("playoff_seed", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "playoff_seed")
    op.drop_column("tournaments", "playoff_size")