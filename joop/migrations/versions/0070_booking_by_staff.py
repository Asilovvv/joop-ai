"""Booking.by_staff: booked on the public booking page from a browser logged in to the business's panel

A receptionist books a caller there, or the owner tries the page. Either way a real booking (reminders, «Касса», the
lists), only not the sign that a customer booked by themselves: the launch step «Первый настоящий клиент» leaves it out.

Revision ID: 0070
Revises: 0069
"""

from alembic import op
import sqlalchemy as sa


revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "by_staff" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("booking")}:
        op.add_column("booking", sa.Column("by_staff", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("booking") as batch:
        batch.drop_column("by_staff")
