"""add editorial pipeline columns to newsletter_issues

Revision ID: c4a1f7d28e55
Revises: b7e2d41a9c03
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a1f7d28e55'
down_revision: Union[str, Sequence[str], None] = 'b7e2d41a9c03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add editorial columns. Existing issues keep working unchanged."""
    op.add_column(
        "newsletter_issues",
        sa.Column("html_body", sa.Text(), nullable=True),
    )
    op.add_column(
        "newsletter_issues",
        sa.Column("big_picture", sa.Text(), nullable=True),
    )
    op.add_column(
        "newsletter_issues",
        sa.Column("editor_feedback", sa.Text(), nullable=True),
    )
    op.add_column(
        "newsletter_issues",
        sa.Column(
            "revision_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove the editorial columns. Other data stays unchanged."""
    op.drop_column("newsletter_issues", "revision_count")
    op.drop_column("newsletter_issues", "editor_feedback")
    op.drop_column("newsletter_issues", "big_picture")
    op.drop_column("newsletter_issues", "html_body")
