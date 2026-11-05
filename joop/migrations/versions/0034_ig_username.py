"""Business.ig_username: the business's own comments under its posts are not customer questions

Revision ID: 0034
Revises: 0033
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "ig_username" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("ig_username", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("ig_username")
