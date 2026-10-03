"""phase4 saved check expiry

Revision ID: 9d13b84c2f4a
Revises: 4b4bdee9575a
Create Date: 2026-10-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d13b84c2f4a"
down_revision: str | Sequence[str] | None = "4b4bdee9575a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("checks") as batch_op:
        batch_op.alter_column(
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE checks SET expires_at = created_at WHERE expires_at IS NULL"))
    with op.batch_alter_table("checks") as batch_op:
        batch_op.alter_column(
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
