"""StockWatch.sent: the «снова в наличии» message reached the customer (for the owner's results)

Revision ID: 0056
Revises: 0055
"""

from alembic import op
import sqlalchemy as sa


revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "sent" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("stockwatch")}:
        op.add_column("stockwatch", sa.Column("sent", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("stockwatch") as batch:
        batch.drop_column("sent")
