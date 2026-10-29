"""saas: subscriptions, payments, prospects

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    # A database created with create_all() before migrations existed may already have these tables.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "subscription" in existing:
        return
    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("status", S(), nullable=False),
        sa.Column("price_som", sa.Integer(), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        sa.Column("paid_until", sa.DateTime(), nullable=True),
        sa.Column("contact_name", S(), nullable=False),
        sa.Column("contact_phone", S(), nullable=False),
        sa.Column("source", S(), nullable=False),
        sa.Column("note", S(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_business_id", "subscription", ["business_id"], unique=True)
    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("amount_som", sa.Integer(), nullable=False),
        sa.Column("method", S(), nullable=False),
        sa.Column("status", S(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("provider_payment_id", S(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_business_id", "payment", ["business_id"])
    op.create_index("ix_payment_provider_payment_id", "payment", ["provider_payment_id"])
    op.create_table(
        "prospect",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", S(), nullable=False),
        sa.Column("niche", S(), nullable=False),
        sa.Column("city", S(), nullable=False),
        sa.Column("contact_name", S(), nullable=False),
        sa.Column("phone", S(), nullable=False),
        sa.Column("instagram", S(), nullable=False),
        sa.Column("notes", S(), nullable=False),
        sa.Column("language", S(), nullable=False),
        sa.Column("status", S(), nullable=False),
        sa.Column("message", S(), nullable=False),
        sa.Column("demo_business_id", sa.Integer(), nullable=True),
        sa.Column("next_step_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["demo_business_id"], ["business.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("prospect")
    op.drop_index("ix_payment_provider_payment_id", table_name="payment")
    op.drop_index("ix_payment_business_id", table_name="payment")
    op.drop_table("payment")
    op.drop_index("ix_subscription_business_id", table_name="subscription")
    op.drop_table("subscription")
