"""Service.stock / stock_min and StockMove: stock for goods sold in the chat (joop/stock.py)

Revision ID: 0041
Revises: 0040
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("service")}
    if "stock" not in columns:
        op.add_column("service", sa.Column("stock", sa.Integer(), nullable=True))
    if "stock_min" not in columns:
        op.add_column("service", sa.Column("stock_min", sa.Integer(), nullable=False, server_default="0"))
    if "stockmove" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "stockmove",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("service_id", sa.Integer(), sa.ForeignKey("service.id"), nullable=False),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("left", sa.Integer(), nullable=False),
            sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("who", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=""),
            sa.Column("order_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_stockmove_business_id", "stockmove", ["business_id"])
        op.create_index("ix_stockmove_service_id", "stockmove", ["service_id"])
        op.create_index("ix_stockmove_order_id", "stockmove", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_stockmove_order_id", table_name="stockmove")
    op.drop_index("ix_stockmove_service_id", table_name="stockmove")
    op.drop_index("ix_stockmove_business_id", table_name="stockmove")
    op.drop_table("stockmove")
    with op.batch_alter_table("service") as batch:
        batch.drop_column("stock_min")
        batch.drop_column("stock")
