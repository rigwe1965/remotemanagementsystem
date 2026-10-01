"""ai ticket triage — category/confidence/triage_status columns on tickets + triage_categories table

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None

_DEFAULT_CATEGORIES = [
    ("device_health", "Devices & Agents",
     "Offline devices, agents not reporting, install/uninstall questions, hostname/metrics questions."),
    ("patch_management", "Patches & Updates",
     "Failed or pending OS/software updates, patch compliance questions."),
    ("alerts_monitoring", "Alerts & Monitoring",
     "Alert rule questions, false positives, threshold tuning."),
    ("scripts_automation", "Scripts & Automation",
     "Requests to run a script or built-in action, automation rule failures."),
    ("mdm_mobile", "MDM & Mobile Devices",
     "Phone enrollment, compliance, remote wipe/lock/lost-mode questions."),
    ("network_discovery", "Network & Discovery",
     "Agentless/network-scan device questions."),
    ("billing_invoicing", "Billing & Invoices",
     "Invoice copies, payment method, charge/Stripe questions."),
    ("account_access", "Account & Access",
     "Password reset, locked account, add/remove user requests."),
    ("backup_recovery", "Backup & Recovery",
     "Backup failure or status questions."),
]


def upgrade():
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("ai_suggested_category", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("ai_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("ai_suggested_reply", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_reasoning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("triage_status", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("auto_resolved", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("triage_model", sa.String(60), nullable=True))
        batch_op.add_column(sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_tickets_category", ["category"])
        batch_op.create_index("ix_tickets_triage_status", ["triage_status"])

    op.create_table(
        "triage_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_resolve_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shadow_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default="0.85"),
        sa.Column("auto_close_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Seed the default taxonomy — all start inactive-for-auto-resolve (auto_resolve_enabled=False,
    # shadow_mode=True) so triage classifies every ticket from day one but nothing auto-resolves
    # until an admin deliberately opts a category in. "other" is NOT seeded here — it is handled
    # as the always-escalate catch-all in code, with no whitelist row that could be flipped on.
    conn = op.get_bind()
    now_fn = "NOW()" if conn.dialect.name == "postgresql" else "CURRENT_TIMESTAMP"
    uuid_fn = "gen_random_uuid()::text" if conn.dialect.name == "postgresql" else None
    import uuid as _uuid
    for code, label, description in _DEFAULT_CATEGORIES:
        row_id = str(_uuid.uuid4())
        op.execute(
            sa.text(
                "INSERT INTO triage_categories "
                "(id, code, label, description, is_active, auto_resolve_enabled, shadow_mode, "
                " confidence_threshold, created_at, updated_at) "
                f"VALUES (:id, :code, :label, :description, true, false, true, 0.85, {now_fn}, {now_fn})"
            ).bindparams(id=row_id, code=code, label=label, description=description)
        )


def downgrade():
    op.drop_table("triage_categories")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_index("ix_tickets_triage_status")
        batch_op.drop_index("ix_tickets_category")
        batch_op.drop_column("triaged_at")
        batch_op.drop_column("triage_model")
        batch_op.drop_column("auto_resolved")
        batch_op.drop_column("triage_status")
        batch_op.drop_column("ai_reasoning")
        batch_op.drop_column("ai_suggested_reply")
        batch_op.drop_column("ai_confidence")
        batch_op.drop_column("ai_suggested_category")
        batch_op.drop_column("category")
