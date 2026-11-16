"""Business.api_booking: the API key may book free times (joop/api.py)

Revision ID: 0061
Revises: 0060
"""

from alembic import op
import sqlalchemy as sa


revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "api_booking" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("api_booking", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("api_booking")
