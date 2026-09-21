"""Make the large online Swiss format a per-tournament opt-in.

Classic internal Swiss events keep playing INTERNAL_SWISS_ROUNDS rounds with no
playoff. The new ``swiss_large_format`` flag (default off) opts a tournament
into field-scaled rounds and an optional top-8/top-16 playoff.
"""

from alembic import op
import sqlalchemy as sa

revision = "e528f8f092f9"
down_revision = "337216afe8c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column(
            "swiss_large_format",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tournaments", "swiss_large_format")
