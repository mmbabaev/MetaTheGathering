"""add payments table

Revision ID: a6b7c8d9e0f1
Revises: f4a5b6c7d8e9
Create Date: 2026-04-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tg_id', sa.BigInteger(), nullable=False),
        sa.Column('tournament_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.String(length=16), nullable=False),
        sa.Column('yookassa_payment_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.Enum('pending', 'succeeded', 'cancelled', name='paymentstatus'), nullable=False),
        sa.Column('confirmation_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('yookassa_payment_id'),
    )
    op.create_index('ix_payments_id', 'payments', ['id'], unique=False)
    op.create_index('ix_payments_tg_id', 'payments', ['tg_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_payments_tg_id', table_name='payments')
    op.drop_index('ix_payments_id', table_name='payments')
    op.drop_table('payments')
    op.execute("DROP TYPE IF EXISTS paymentstatus")
