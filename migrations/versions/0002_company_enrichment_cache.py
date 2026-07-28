"""company enrichment cache — domain-keyed company facts

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_enrichment",
        sa.Column("domain", sa.String(), primary_key=True),
        sa.Column("data", sa.JSON()),
        sa.Column("updated_at", sa.DateTime()),
    )


def downgrade():
    op.drop_table("company_enrichment")
