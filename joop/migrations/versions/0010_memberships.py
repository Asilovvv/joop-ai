"""memberships: passes and packages of visits

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    if "membership" in set(sa.inspect(op.get_bind()).get_table_names()):
        return  # created by create_all() before migrations
    op.create_table(
        "membership",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", S(), nullable=False),
        sa.Column("phone_key", S(), nullable=False),
        sa.Column("customer_phone", S(), nullable=False),
        sa.Column("title", S(), nullable=False),
        sa.Column("visits_total", sa.Integer(), nullable=False),
        sa.Column("visits_used", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_membership_business_id", "membership", ["business_id"])
    op.create_index("ix_membership_phone_key", "membership", ["phone_key"])


def downgrade() -> None:
    op.drop_table("membership")
