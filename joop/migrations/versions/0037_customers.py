"""Customer: notes and tags on the customer card (joop/customers.py)

Revision ID: 0037
Revises: 0036
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "customer" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "customer",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
            sa.Column("tags", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_customer_business_id", "customer", ["business_id"])
        op.create_index("ix_customer_key", "customer", ["key"])


def downgrade() -> None:
    op.drop_index("ix_customer_key", table_name="customer")
    op.drop_index("ix_customer_business_id", table_name="customer")
    op.drop_table("customer")
