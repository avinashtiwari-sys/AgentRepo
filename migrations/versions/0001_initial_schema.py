"""initial schema — leads table

Revision ID: 0001
Revises:
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "leads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("first_name", sa.String()),
        sa.Column("last_name", sa.String()),
        sa.Column("company", sa.String()),
        sa.Column("domain", sa.String()),
        sa.Column("lead_source", sa.String()),
        sa.Column("status", sa.String(), nullable=False, server_default="received"),
        sa.Column("enrichment_data", sa.JSON()),
        sa.Column("assigned_rep", sa.String()),
        sa.Column("raw_payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_leads_status", "leads", ["status"])


def downgrade():
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_table("leads")
