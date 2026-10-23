"""baseline existing database

Revision ID: 9c518f985b38
Revises: 
Create Date: 2026-10-22 18:07:16.641931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c518f985b38'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    """Mark the existing database schema as the initial baseline."""
    pass


def downgrade() -> None:
    """Keep the existing database schema intact."""
    pass

