"""Business.test_link_code: the secret part of the panel's «Написать боту» link

Revision ID: 0049
Revises: 0048
"""

from alembic import op
import sqlalchemy as sa


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "test_link_code" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("test_link_code", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("test_link_code")
