"""Booking.return_sent_at: when the automatic invitation to come again went out

The automatic invitation and the one the owner sends from «Пустые окна» did not know about each other, and a customer
could get both within days. With the time kept, each leaves a customer alone for two weeks after the other.

Revision ID: 0067
Revises: 0066
"""

from alembic import op
import sqlalchemy as sa


revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "return_sent_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("booking")}:
        op.add_column("booking", sa.Column("return_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("booking") as batch:
        batch.drop_column("return_sent_at")
