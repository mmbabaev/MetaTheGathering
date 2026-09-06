"""allow Magic Oculus imports without AetherHub

Revision ID: 9a8747d47da4
Revises: 7167a65fad51
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9a8747d47da4"
down_revision: Union[str, Sequence[str], None] = "7167a65fad51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("magicoculus_imports") as batch_op:
        batch_op.alter_column(
            "aetherhub_url",
            existing_type=sa.String(length=512),
            nullable=True,
        )


def downgrade() -> None:
    imports = sa.table("magicoculus_imports", sa.column("aetherhub_url", sa.String(length=512)))
    op.get_bind().execute(sa.delete(imports).where(imports.c.aetherhub_url.is_(None)))
    with op.batch_alter_table("magicoculus_imports") as batch_op:
        batch_op.alter_column(
            "aetherhub_url",
            existing_type=sa.String(length=512),
            nullable=False,
        )
