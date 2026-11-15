"""Business.missed_call_token and Business.wa_missed_call_template: a missed call becomes a WhatsApp message

Revision ID: 0058
Revises: 0057
"""

from alembic import op
import sqlalchemy as sa


revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}
    for name in ("missed_call_token", "wa_missed_call_template"):
        if name not in have:
            op.add_column("business", sa.Column(name, sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("wa_missed_call_template")
        batch.drop_column("missed_call_token")
