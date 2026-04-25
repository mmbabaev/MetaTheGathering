"""add feature_flags table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-25

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'feature_flags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('description', sa.String(255), nullable=False),
        sa.Column('value_type', sa.String(16), nullable=False),
        sa.Column('default_value', sa.String(64), nullable=False),
        sa.Column('current_value', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feature_flags_id', 'feature_flags', ['id'])
    op.create_index('ix_feature_flags_name', 'feature_flags', ['name'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_feature_flags_name', table_name='feature_flags')
    op.drop_index('ix_feature_flags_id', table_name='feature_flags')
    op.drop_table('feature_flags')
