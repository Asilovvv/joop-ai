"""Business.telegram_bot_username for t.me links on the counter card

Revision ID: 0032
Revises: 0031
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "telegram_bot_username" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("telegram_bot_username", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("telegram_bot_username")
