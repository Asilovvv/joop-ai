"""Service.sold_out (stock reached zero, not the owner's stop list) and an index on booking.conversation_id

Revision ID: 0042
Revises: 0041
"""

from alembic import op
import sqlalchemy as sa


revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "sold_out" not in {c["name"] for c in sa.inspect(bind).get_columns("service")}:
        op.add_column("service", sa.Column("sold_out", sa.Boolean(), nullable=False, server_default=sa.false()))
        # items the stock emptied before this column existed: they were sold out, not stopped by hand
        op.execute("UPDATE service SET sold_out = 1 WHERE stock = 0 AND available = 0")
    if "ix_booking_conversation_id" not in {i["name"] for i in sa.inspect(bind).get_indexes("booking")}:
        op.create_index("ix_booking_conversation_id", "booking", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_booking_conversation_id", table_name="booking")
    with op.batch_alter_table("service") as batch:
        batch.drop_column("sold_out")
