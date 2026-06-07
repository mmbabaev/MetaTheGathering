"""add round pairing match scores

Revision ID: 9fc68f844468
Revises: cb06771cfa48
Create Date: 2026-06-07 00:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9fc68f844468"
down_revision: Union[str, Sequence[str], None] = "cb06771cfa48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("round_pairings", sa.Column("player_wins", sa.Integer(), nullable=True))
    op.add_column("round_pairings", sa.Column("opponent_wins", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("round_pairings", "opponent_wins")
    op.drop_column("round_pairings", "player_wins")
