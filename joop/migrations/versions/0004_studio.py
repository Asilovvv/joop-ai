"""studio: requests for websites, slides and menus

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

S = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    if "studiorequest" in set(sa.inspect(op.get_bind()).get_table_names()):
        return  # created by create_all() before migrations
    op.create_table(
        "studiorequest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", S(), nullable=False),
        sa.Column("business_name", S(), nullable=False),
        sa.Column("contact_name", S(), nullable=False),
        sa.Column("phone", S(), nullable=False),
        sa.Column("niche", S(), nullable=False),
        sa.Column("description", S(), nullable=False),
        sa.Column("status", S(), nullable=False),
        sa.Column("price_som", sa.Integer(), nullable=False),
        sa.Column("content_json", S(), nullable=False),
        sa.Column("public_slug", S(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("source", S(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_studiorequest_public_slug", "studiorequest", ["public_slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_studiorequest_public_slug", table_name="studiorequest")
    op.drop_table("studiorequest")
