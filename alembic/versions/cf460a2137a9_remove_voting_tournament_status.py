"""Remove the VOTING tournament status.

Revision ID: cf460a2137a9
Revises: 712642f519b0

Existing VOTING tournaments become ONGOING. The downgrade restores the enum
value, but cannot distinguish those tournaments from tournaments that were
already ONGOING before the upgrade.
"""

from alembic import op

revision = "cf460a2137a9"
down_revision = "712642f519b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tournaments SET status = 'ONGOING' WHERE status = 'VOTING'")

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("ALTER TYPE tournamentstatus RENAME TO tournamentstatus_old")
    op.execute("CREATE TYPE tournamentstatus AS ENUM ('REGISTRATION', 'ONGOING', 'CLOSED')")
    op.execute(
        "ALTER TABLE tournaments ALTER COLUMN status TYPE tournamentstatus "
        "USING status::text::tournamentstatus"
    )
    op.execute("DROP TYPE tournamentstatus_old")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("ALTER TYPE tournamentstatus RENAME TO tournamentstatus_old")
    op.execute("CREATE TYPE tournamentstatus AS ENUM ('REGISTRATION', 'ONGOING', 'VOTING', 'CLOSED')")
    op.execute(
        "ALTER TABLE tournaments ALTER COLUMN status TYPE tournamentstatus "
        "USING status::text::tournamentstatus"
    )
    op.execute("DROP TYPE tournamentstatus_old")
