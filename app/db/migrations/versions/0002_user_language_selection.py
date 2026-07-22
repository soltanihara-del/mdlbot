"""Track explicit user language selection.

Revision ID: 0002_user_language_selection
Revises: 0001_initial_schema
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_user_language_selection"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language_selected_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "language_selected_at")
