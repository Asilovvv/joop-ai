"""Page bookings staff made while #313 was in main: real bookings again

For about fifteen hours on 27 Nov 2026 a booking made on the public booking page from a browser logged in to the
business's panel got the panel test chat's channel ("console"), which hides it from «Записи», «Касса» and the
reminders while its time stays taken. 0070 added Booking.by_staff for these; this marks the ones written meanwhile.
A page booking never had that channel otherwise: the page writes "" (api.book).

Revision ID: 0071
Revises: 0070
"""

from alembic import op


revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE booking SET by_staff = 1, channel = '' WHERE source = 'page' AND channel = 'console'")


def downgrade() -> None:
    pass  # the rows stay real bookings: hiding them again would lose customers
