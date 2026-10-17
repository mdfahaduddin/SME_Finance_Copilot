"""ChatSession.PinnedAt: pinned conversations stay at the top of the list

Additive only: a nullable column; existing conversations stay unpinned. No data is changed or removed.

Revision ID: 7c3d9e1a5b42
Revises: 4b1e6c2f8a90
Create Date: 2026-10-13 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c3d9e1a5b42'
down_revision: Union[str, Sequence[str], None] = '4b1e6c2f8a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ChatSession') as batch:
        batch.add_column(sa.Column('PinnedAt', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Drops only the column added above: conversations lose their pinned state, nothing else.
    with op.batch_alter_table('ChatSession') as batch:
        batch.drop_column('PinnedAt')
