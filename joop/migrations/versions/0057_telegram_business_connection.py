"""Business.telegram_business_connection: the owner's own Telegram Business connection the bot may answer through

Revision ID: 0057
Revises: 0056
"""

from alembic import op
import sqlalchemy as sa


revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "telegram_business_connection" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("telegram_business_connection", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("telegram_business_connection")
