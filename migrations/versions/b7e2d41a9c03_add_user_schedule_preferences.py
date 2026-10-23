"""add user schedule preferences

Revision ID: b7e2d41a9c03
Revises: 9c518f985b38
Create Date: 2026-10-23 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2d41a9c03'
down_revision: Union[str, Sequence[str], None] = '9c518f985b38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add schedule columns. Existing users get safe default values."""
    op.add_column(
        "users",
        sa.Column(
            "preferred_time",
            sa.Time(),
            server_default="08:00:00",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("preferred_day", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=50),
            server_default="Asia/Kolkata",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_run_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    """Remove the schedule columns. Other user data stays unchanged."""
    op.drop_column("users", "last_run_date")
    op.drop_column("users", "timezone")
    op.drop_column("users", "preferred_day")
    op.drop_column("users", "preferred_time")
