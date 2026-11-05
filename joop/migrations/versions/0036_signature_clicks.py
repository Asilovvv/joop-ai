"""SignatureClick: visits to Joop's site from a free business's AI signature

Revision ID: 0036
Revises: 0035
"""

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "signatureclick" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "signatureclick",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_signatureclick_business_id", "signatureclick", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_signatureclick_business_id", table_name="signatureclick")
    op.drop_table("signatureclick")
