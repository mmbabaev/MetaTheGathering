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
    internal_imports = (
        op.get_bind()
        .execute(sa.select(sa.func.count()).select_from(imports).where(imports.c.aetherhub_url.is_(None)))
        .scalar_one()
    )
    if internal_imports:
        raise RuntimeError(
            "Cannot make magicoculus_imports.aetherhub_url non-nullable: "
            f"{internal_imports} internal Swiss import journal row(s) would be lost"
        )
    with op.batch_alter_table("magicoculus_imports") as batch_op:
        batch_op.alter_column(
            "aetherhub_url",
            existing_type=sa.String(length=512),
            nullable=False,
        )
