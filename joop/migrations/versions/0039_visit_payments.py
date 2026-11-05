"""Booking.paid_som / paid_method / paid_at: what the customer paid after the visit (joop/cash.py)

Revision ID: 0039
Revises: 0038
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("booking")}
    if "paid_som" not in columns:
        op.add_column("booking", sa.Column("paid_som", sa.Integer(), nullable=False, server_default="0"))
    if "paid_method" not in columns:
        op.add_column("booking", sa.Column("paid_method", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))
    if "paid_at" not in columns:
        op.add_column("booking", sa.Column("paid_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("booking") as batch:
        batch.drop_column("paid_at")
        batch.drop_column("paid_method")
        batch.drop_column("paid_som")
