"""PanelUser.staff_id: a master's own login sees only her bookings, customers and cash

Revision ID: 0040
Revises: 0039
"""

from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "staff_id" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("paneluser")}:
        with op.batch_alter_table("paneluser") as batch:
            batch.add_column(sa.Column("staff_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_paneluser_staff_id", "staff", ["staff_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("paneluser") as batch:
        batch.drop_column("staff_id")
