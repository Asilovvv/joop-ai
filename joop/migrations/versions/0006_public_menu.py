"""public menu with QR codes: two business columns

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}
    if "menu_enabled" not in columns:
        op.add_column("business", sa.Column("menu_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "menu_chat_url" not in columns:
        op.add_column("business", sa.Column("menu_chat_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("menu_chat_url")
        batch.drop_column("menu_enabled")
