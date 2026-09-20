"""Add custom_title to tournament_creation_plans.

Название турнира по желанию создателя (Концеход): пусто → авто «Концеход Pauper #N».
"""

from alembic import op
import sqlalchemy as sa

revision = "842c718201a6"
down_revision = "b516420f583a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tournament_creation_plans", sa.Column("custom_title", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("tournament_creation_plans", "custom_title")