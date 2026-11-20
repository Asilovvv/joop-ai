"""Business.page_booking: customers book a free time themselves on the public page, without a chat

Off until the owner turns it on in «Онлайн-страница»: a page that so far only invited customers to write must not
start taking bookings on its own.

Revision ID: 0064
Revises: 0063
"""

from alembic import op
import sqlalchemy as sa


revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "page_booking" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("page_booking", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("page_booking")
