#!/usr/bin/env python3
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from productization_v1.operator_projection import project_operator_state


PUBLIC = {
    "profile": "public-pages",
    "console": {
        "mode": "public-pages",
        "data_classification": "public",
        "public_opt_in": True,
    },
}
PRIVATE = {
    "profile": "private-no-public-console",
    "console": {
        "mode": "private-none",
        "data_classification": "private",
        "public_opt_in": False,
    },
}
INSTALLATION = {
    "installation_id": "aibb-reference-0001",
    "versions": {
        "core": "1.0.0",
        "workflow": "1.0.0",
        "config_schema": "ai-bb-productization:v1",
        "private_internal_version": "must-not-project",
    },
}
BASE = {
    "main_status": "MAIN_GREEN",
    "scheduler_status": "healthy",
    "workflow_status": "healthy",
    "permission_status": "ok",
    "recovery_status": "",
    "intentional_idle": False,
    "work_in_progress": False,
    "review_needed": False,
    "completed_accepted": False,
    "installed_release_id": "release:1.0.0",
    "available_release_id": "release:1.1.0",
    "last_accepted_release_id": "release:1.0.0",
    "evidence": {
        "source_release": "release:1.0.0",
        "measured_at": "2026-09-18T15:00:00Z",
        "freshness": "current",
        "scope": "release",
        "acceptance_status": "accepted",
    },
}


def project(**overrides):
    facts = {**BASE, **overrides}
    return project_operator_state(
        facts, project_config=PUBLIC, installation_state=INSTALLATION
    )


def must_fail(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError("expected fail-closed validation")


# Healthy intentional idle is distinct from an inability to run.
idle = project(intentional_idle=True)
assert idle["operator_state"] == "healthy_idle"
assert idle["operator_reason"] == "intentional_idle"
assert idle["operator_action"] == "none"

failed_scheduler = project(intentional_idle=True, scheduler_status="failed")
assert failed_scheduler["operator_state"] == "recovery_needed"
assert failed_scheduler["operator_reason"] == "scheduler_failure"

unknown_idle = project(intentional_idle=False)
assert unknown_idle["operator_state"] == "recovery_needed"
assert unknown_idle["operator_reason"] == "healthy_idle_not_proven"

# Work, exact-head review, and accepted completion are distinct classifications.
active = project(work_in_progress=True)
assert active["operator_state"] == "work_in_progress"
review = project(work_in_progress=True, review_needed=True)
assert review["operator_state"] == "review_needed"
completed = project(completed_accepted=True)
assert completed["operator_state"] == "completed_accepted"
assert completed["operator_action"] == "none"
must_fail(
    project_operator_state,
    {**BASE, "completed_accepted": True, "work_in_progress": True},
    project_config=PUBLIC,
)

# Stale evidence remains visible even when completion is accepted.
stale = project(
    completed_accepted=True,
    evidence={**BASE["evidence"], "freshness": "stale"},
)
assert stale["operator_state"] == "completed_accepted"
assert stale["operator_action"] == "refresh_acceptance_evidence"
assert stale["evidence"]["freshness"] == "stale"

# Human Required uses a strict ten-field whitelist and exposes incompleteness.
human = {
    "reason": "repository visibility approval required",
    "action": "approve requested visibility setting",
    "surface": "repository settings",
    "urgency": "normal",
    "safety_privacy": "may change public exposure",
    "evidence_link": "Issue:#23",
    "resolver": "repository owner",
    "defer_cancel": "may defer or cancel",
    "expiry_staleness": "revalidate before action",
    "resume_path": "resume canonical task after approval",
}
human_out = project(human_required=human)
assert human_out["operator_state"] == "human_required"
assert human_out["human_required_complete"] is True
assert human_out["human_required_missing_fields"] == []

incomplete = project(human_required={"reason": "approval required"})
assert incomplete["operator_state"] == "human_required"
assert incomplete["human_required_complete"] is False
assert "action" in incomplete["human_required_missing_fields"]
assert "action" not in incomplete["human_required"]
must_fail(
    project_operator_state,
    {**BASE, "human_required": {**human, "raw_issue_body": "untrusted"}},
    project_config=PUBLIC,
)

# Deterministic recovery facts are safety-prioritized.
assert project(main_status="MAIN_RED")["operator_reason"] == "main_red"
assert project(permission_status="missing")["operator_reason"] == "missing_permission"
assert project(recovery_status="expired_unreclaimed")["operator_reason"] == "expired_ownership"
assert project(recovery_status="history_unsafe")["operator_reason"] == "history_unsafe"

# Public/private profile classification is fail-closed.
private_out = project_operator_state(BASE, project_config=PRIVATE)
assert private_out["profile"] == {
    "profile": "private-no-public-console",
    "console_mode": "private-none",
    "data_classification": "private",
    "public_opt_in": False,
}
bad_private = {
    "profile": "private-no-public-console",
    "console": {
        "mode": "public-pages",
        "data_classification": "private",
        "public_opt_in": True,
    },
}
must_fail(project_operator_state, BASE, project_config=bad_private)

# Release/install projection is whitelist-only and shows upgrade availability.
release = project()
assert release["release"]["upgrade_available"] is True
assert release["installation"]["installation_id"] == "aibb-reference-0001"
assert "private_internal_version" not in release["installation"]["installed_versions"]

# Missing evidence is explicit rather than silently green/current.
without_evidence = {key: value for key, value in BASE.items() if key != "evidence"}
missing = project_operator_state(without_evidence, project_config=PUBLIC)
assert missing["evidence"]["freshness"] == "missing"
assert missing["evidence"]["acceptance_status"] == "unknown"

# Unknown/raw payload fields and credential-like values fail closed.
must_fail(
    project_operator_state,
    {**BASE, "raw_issue_body": "do not project me"},
    project_config=PUBLIC,
)
must_fail(
    project_operator_state,
    {
        **BASE,
        "human_required": {
            **human,
            "reason": "Authorization: Bearer should-never-project",
        },
    },
    project_config=PUBLIC,
)

print("PRODUCTIZATION_PHASE2_OPERATOR_PROJECTION_OK")
