"""Business.example_niche: which niche's sign-up example the business got

Revision ID: 0050
Revises: 0049
"""

from alembic import op
import sqlalchemy as sa


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "example_niche" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("business")}:
        op.add_column("business", sa.Column("example_niche", sa.String(), nullable=False, server_default=""))
    # Until now the example was recognised by the current niche: keep that for existing businesses.
    op.execute("UPDATE business SET example_niche = niche WHERE example_niche = ''")


def downgrade() -> None:
    with op.batch_alter_table("business") as batch:
        batch.drop_column("example_niche")
