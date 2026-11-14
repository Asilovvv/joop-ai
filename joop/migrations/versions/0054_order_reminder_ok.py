"""Order.reminder_ok: the reorder reminder actually reached the customer (joop/reorders.py)

Revision ID: 0054
Revises: 0053
"""

from alembic import op
import sqlalchemy as sa


revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "reminder_ok" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("order")}:
        op.add_column("order", sa.Column("reminder_ok", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("order") as batch:
        batch.drop_column("reminder_ok")
