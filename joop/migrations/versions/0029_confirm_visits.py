"""confirming a visit from the reminder: Booking.confirmed_at, Business.release_unconfirmed_hours

Revision ID: 0029
Revises: 0028
"""

from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "confirmed_at" not in {c["name"] for c in sa.inspect(bind).get_columns("booking")}:
        op.add_column("booking", sa.Column("confirmed_at", sa.DateTime(), nullable=True))
    if "release_unconfirmed_hours" not in {c["name"] for c in sa.inspect(bind).get_columns("business")}:
        op.add_column("business", sa.Column("release_unconfirmed_hours", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("release_unconfirmed_hours")
    with op.batch_alter_table("booking") as batch:
        batch.drop_column("confirmed_at")
