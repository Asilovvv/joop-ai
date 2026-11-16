"""Message.kyrgyz: how an AI reply to a Kyrgyz message went out (ky, untranslated, numbers)

Revision ID: 0062
Revises: 0061
"""

from alembic import op
import sqlalchemy as sa


revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "kyrgyz" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("message")}:
        op.add_column("message", sa.Column("kyrgyz", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("message") as batch:
        batch.drop_column("kyrgyz")
