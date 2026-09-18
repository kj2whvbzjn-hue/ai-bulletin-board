from pathlib import Path

html = Path("pages/index.html").read_text(encoding="utf-8")

# Phase-2B consumes only the sanitized Phase-2A projection and must not infer a
# customer state from lower-level diagnostics when that projection is absent.
for state, label in {
    "healthy_idle": "Healthy / Idle",
    "work_in_progress": "Work in progress",
    "review_needed": "Review needed",
    "human_required": "Human action needed",
    "recovery_needed": "Recovery needed",
    "completed_accepted": "Completed / Accepted",
}.items():
    assert f"{state}:'{label}'" in html

required = [
    "ai-bb-operator-projection:v1",
    "data&&data.operator_projection",
    "diagnostics are not promoted to a guessed customer state",
    "Supported operator language: English",
    "Advanced diagnostics",
    'aria-label="Classification-aware operator status"',
    'role="status"',
    "operator-advanced>summary:focus-visible",
    "overflow-wrap:anywhere",
]
for snippet in required:
    assert snippet in html, f"missing Phase-2B console contract: {snippet}"

# Human Required must keep all ten structured fields and remain ahead of
# lower-priority metadata in the narrow single-column layout.
for field in [
    "reason", "action", "surface", "urgency", "safety_privacy",
    "evidence_link", "resolver", "defer_cancel", "expiry_staleness", "resume_path",
]:
    assert f"'{field}'" in html
assert ".operator-human{order:-1" in html
assert "@media(max-width:900px){.operator-meta{grid-template-columns:1fr}" in html

# Existing sanitized Phase-2A release/evidence/profile fields are rendered,
# while incomplete Human Required data is explicitly called out.
for field in [
    "public_opt_in", "installed_release_id", "available_release_id",
    "last_accepted_release_id", "source_release", "measured_at",
    "freshness", "scope", "acceptance_status", "human_required_missing_fields",
]:
    assert field in html

print("PRODUCTIZATION_PHASE2_CONSOLE_REGRESSION_OK")
