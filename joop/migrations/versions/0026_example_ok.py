"""business.example_ok: the owner confirmed that rows still equal to the sign-up example are real

Revision ID: 0026
Revises: 0025
"""

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}
    if "example_ok" not in columns:
        op.add_column("business", sa.Column("example_ok", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("example_ok")
