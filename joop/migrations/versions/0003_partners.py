"""partners: referral program

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    if "partner" in set(sa.inspect(op.get_bind()).get_table_names()):
        return  # created by create_all() before migrations
    op.create_table(
        "partner",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", S(), nullable=False),
        sa.Column("phone", S(), nullable=False),
        sa.Column("code", S(), nullable=False),
        sa.Column("secret", S(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_partner_code", "partner", ["code"], unique=True)
    op.create_index("ix_partner_secret", "partner", ["secret"], unique=True)
    op.create_table(
        "referral",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["partner_id"], ["partner.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referral_business_id", "referral", ["business_id"], unique=True)
    op.create_index("ix_referral_partner_id", "referral", ["partner_id"])
    op.create_table(
        "partnerpayout",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("amount_som", sa.Integer(), nullable=False),
        sa.Column("note", S(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["partner_id"], ["partner.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_partnerpayout_partner_id", "partnerpayout", ["partner_id"])


def downgrade() -> None:
    op.drop_index("ix_partnerpayout_partner_id", table_name="partnerpayout")
    op.drop_table("partnerpayout")
    op.drop_index("ix_referral_partner_id", table_name="referral")
    op.drop_index("ix_referral_business_id", table_name="referral")
    op.drop_table("referral")
    op.drop_index("ix_partner_secret", table_name="partner")
    op.drop_index("ix_partner_code", table_name="partner")
    op.drop_table("partner")
