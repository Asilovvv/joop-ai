"""subscription plan: free (one master, Joop signature) or pro

Revision ID: 0025
Revises: 0024
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("subscription")}
    if "plan" not in columns:
        op.add_column("subscription", sa.Column("plan", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="pro"))


def downgrade() -> None:
    with op.batch_alter_table("subscription") as batch:
        batch.drop_column("plan")
