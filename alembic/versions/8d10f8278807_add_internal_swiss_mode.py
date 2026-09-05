"""add internal Swiss tournament mode

Revision ID: 8d10f8278807
Revises: 462d69c18f40
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8d10f8278807"
down_revision: Union[str, Sequence[str], None] = "462d69c18f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column("engine_mode", sa.String(length=24), server_default="aetherhub", nullable=False),
    )
    op.add_column("tournaments", sa.Column("swiss_rounds", sa.Integer(), nullable=True))
    op.add_column("participants", sa.Column("swiss_initial_rank", sa.Integer(), nullable=True))
    with op.batch_alter_table("round_pairings") as batch_op:
        batch_op.add_column(sa.Column("player_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("opponent_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_round_pairings_player_user_id_users",
            "users",
            ["player_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_round_pairings_opponent_user_id_users",
            "users",
            ["opponent_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("round_pairings") as batch_op:
        batch_op.drop_constraint("fk_round_pairings_opponent_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_round_pairings_player_user_id_users", type_="foreignkey")
        batch_op.drop_column("opponent_user_id")
        batch_op.drop_column("player_user_id")
    op.drop_column("participants", "swiss_initial_rank")
    op.drop_column("tournaments", "swiss_rounds")
    op.drop_column("tournaments", "engine_mode")
