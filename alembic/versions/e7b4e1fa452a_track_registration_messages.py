"""Track latest tournament registration messages.

Revision ID: e7b4e1fa452a
Revises: cf460a2137a9
"""

import sqlalchemy as sa

from alembic import op

revision = "e7b4e1fa452a"
down_revision = "cf460a2137a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tournament_registration_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("base_text", sa.Text(), nullable=False),
        sa.Column("button_url", sa.String(length=512), nullable=True),
        sa.Column("rendered_participant_count", sa.Integer(), nullable=False),
        sa.Column("edit_disabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "chat_id", name="uq_tournament_registration_message_target"),
    )
    op.create_index(
        "ix_tournament_registration_messages_tournament_id",
        "tournament_registration_messages",
        ["tournament_id"],
    )
    op.create_index(
        "ix_tournament_registration_messages_edit_disabled_at",
        "tournament_registration_messages",
        ["edit_disabled_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tournament_registration_messages_edit_disabled_at",
        table_name="tournament_registration_messages",
    )
    op.drop_index(
        "ix_tournament_registration_messages_tournament_id",
        table_name="tournament_registration_messages",
    )
    op.drop_table("tournament_registration_messages")
