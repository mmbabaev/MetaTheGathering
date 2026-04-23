"""add tournament aetherhub_import_time

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tournaments', sa.Column('aetherhub_import_time', sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column('tournaments', 'aetherhub_import_time')
