"""Order.sent_at: when staff marked the order «В пути» or «Готов к выдаче»

Revision ID: 0051
Revises: 0050
"""

from alembic import op
import sqlalchemy as sa


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "sent_at" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("order")}:
        op.add_column("order", sa.Column("sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("order") as batch:
        batch.drop_column("sent_at")
