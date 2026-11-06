"""Booking.receipt_at: the fiscal receipt for this payment was printed on the business's own cash register (ККМ)

Revision ID: 0044
Revises: 0043
"""

from alembic import op
import sqlalchemy as sa


revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "receipt_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("booking")}:
        op.add_column("booking", sa.Column("receipt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("booking") as batch:
        batch.drop_column("receipt_at")
