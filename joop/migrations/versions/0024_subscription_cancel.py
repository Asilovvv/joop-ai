"""subscription cancel: when the owner cancelled and why

Revision ID: 0024
Revises: 0023
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("subscription")}
    if "cancelled_at" not in columns:
        op.add_column("subscription", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    if "cancel_reason" not in columns:
        op.add_column("subscription", sa.Column("cancel_reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("subscription") as batch:
        batch.drop_column("cancel_reason")
        batch.drop_column("cancelled_at")
