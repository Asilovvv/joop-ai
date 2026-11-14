"""Order.reminded_at: when the customer was reminded to repeat the order (joop/reorders.py)

Revision ID: 0052
Revises: 0051
"""

from alembic import op
import sqlalchemy as sa


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "reminded_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("order")}:
        op.add_column("order", sa.Column("reminded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("order") as batch:
        batch.drop_column("reminded_at")
