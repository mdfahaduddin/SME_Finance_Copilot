"""FinProduct.Currency: the currency of a product's amount limits

Additive only: existing rows get 'USD' (every product so far was priced in USD). No data is changed or removed.

Revision ID: 4b1e6c2f8a90
Revises: 9d7a81007930
Create Date: 2026-10-13 17:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4b1e6c2f8a90'
down_revision: Union[str, Sequence[str], None] = '9d7a81007930'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('FinProduct') as batch:
        batch.add_column(sa.Column('Currency', sa.String(length=3), server_default='USD', nullable=False))


def downgrade() -> None:
    # Drops only the column added above (every value was USD unless a product was added in another currency).
    with op.batch_alter_table('FinProduct') as batch:
        batch.drop_column('Currency')
