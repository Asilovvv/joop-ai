"""Business.admin_bot: the Telegram bot the alert chats were linked through

Another bot cannot write to them, so after the owner switches bots they no longer count as getting alerts.

Revision ID: 0063
Revises: 0062
"""

from alembic import op
import sqlalchemy as sa


revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "admin_bot" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("admin_bot", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("admin_bot")
