"""Productization v1 Phase-2A sanitized operator projection.

The input to this module is normalized, already-derived control-plane facts. It
never consumes raw Issue/comment payloads and it emits only an explicit
whitelist of customer/operator fields.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .core import validate_persisted_input

OPERATOR_STATES = {
    "healthy_idle",
    "work_in_progress",
    "review_needed",
    "human_required",
    "recovery_needed",
    "completed_accepted",
}
HUMAN_REQUIRED_FIELDS = (
    "reason",
    "action",
    "surface",
    "urgency",
    "safety_privacy",
    "evidence_link",
    "resolver",
    "defer_cancel",
    "expiry_staleness",
    "resume_path",
)
EVIDENCE_FIELDS = (
    "source_release",
    "measured_at",
    "freshness",
    "scope",
    "acceptance_status",
)
_ALLOWED_FACTS = {
    "main_status",
    "scheduler_status",
    "workflow_status",
    "permission_status",
    "recovery_status",
    "intentional_idle",
    "work_in_progress",
    "review_needed",
    "completed_accepted",
    "human_required",
    "evidence",
    "installed_release_id",
    "available_release_id",
    "last_accepted_release_id",
}
_CREDENTIAL_LIKE = re.compile(
    r"(?i)(?:authorization\s*:|bearer\s+|token\s*=|api[_-]?key\s*=|"
    r"password\s*=|cookie\s*:|private[_ -]?key)"
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:/#@+\-]{1,240}$")
_MAIN = {"MAIN_GREEN", "MAIN_RED", "MAIN_UNKNOWN"}
_HEALTH = {"healthy", "failed", "unknown"}
_PERMISSION = {"ok", "missing", "unknown"}
_RECOVERY = {
    "",
    "active",
    "expiring",
    "expired_unreclaimed",
    "reclaimed",
    "released",
    "completed",
    "history_unsafe",
}
_FRESHNESS = {"current", "stale", "missing"}
_EVIDENCE_SCOPE = {"component", "release", "installation", "unknown"}
_ACCEPTANCE = {"accepted", "pending", "not_accepted", "unknown"}


def _text(value: Any, name: str, limit: int = 280) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = " ".join(value.split())
    if not text or len(text) > limit or _CREDENTIAL_LIKE.search(text):
        raise ValueError(f"unsafe or empty {name}")
    return text


def _safe_id(value: Any, name: str, *, allow_empty: bool = True) -> str:
    if value in (None, "") and allow_empty:
        return ""
    text = _text(value, name, 240)
    if _SAFE_ID.fullmatch(text) is None or "://" in text or "?" in text or "=" in text:
        raise ValueError(f"unsafe {name}")
    return text


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _enum(value: Any, allowed: set[str], name: str) -> str:
    if value not in allowed:
        raise ValueError(f"invalid {name}")
    return str(value)


def _validate_profile(project_config: Mapping[str, Any]) -> dict[str, Any]:
    validate_persisted_input(project_config)
    profile = project_config.get("profile")
    console = project_config.get("console")
    if not isinstance(console, Mapping):
        raise ValueError("project_config.console must be an object")
    mode = console.get("mode")
    classification = console.get("data_classification")
    public_opt_in = console.get("public_opt_in")
    if not isinstance(public_opt_in, bool):
        raise ValueError("console.public_opt_in must be boolean")
    if profile == "public-pages":
        if (mode, classification, public_opt_in) != ("public-pages", "public", True):
            raise ValueError("public-pages requires public classification and explicit opt-in")
    elif profile == "private-no-public-console":
        if (mode, classification, public_opt_in) != ("private-none", "private", False):
            raise ValueError("private-no-public-console forbids public projection")
    else:
        raise ValueError("unsupported productization profile")
    return {
        "profile": profile,
        "console_mode": mode,
        "data_classification": classification,
        "public_opt_in": public_opt_in,
    }


def _project_installation(installation_state: Mapping[str, Any] | None) -> dict[str, Any]:
    if installation_state is None:
        return {"installation_id": "", "installed_versions": {}}
    validate_persisted_input(installation_state)
    installation_id = _safe_id(
        installation_state.get("installation_id"), "installation_id", allow_empty=False
    )
    versions = installation_state.get("versions")
    if not isinstance(versions, Mapping):
        raise ValueError("installation_state.versions must be an object")
    allowed = ("core", "workflow", "config_schema")
    projected = {}
    for key in allowed:
        if key in versions:
            projected[key] = _safe_id(versions[key], f"versions.{key}", allow_empty=False)
    return {"installation_id": installation_id, "installed_versions": projected}


def _project_human_required(value: Any) -> tuple[dict[str, str] | None, list[str]]:
    if value is None:
        return None, []
    if not isinstance(value, Mapping):
        raise ValueError("human_required must be an object")
    unknown = set(value) - set(HUMAN_REQUIRED_FIELDS)
    if unknown:
        raise ValueError("human_required contains non-whitelisted fields")
    projected: dict[str, str] = {}
    missing = []
    for field in HUMAN_REQUIRED_FIELDS:
        raw = value.get(field)
        if raw in (None, ""):
            missing.append(field)
        else:
            projected[field] = _text(raw, f"human_required.{field}")
    return projected, missing


def _project_evidence(value: Any) -> dict[str, str]:
    if value is None:
        return {
            "source_release": "",
            "measured_at": "",
            "freshness": "missing",
            "scope": "unknown",
            "acceptance_status": "unknown",
        }
    if not isinstance(value, Mapping):
        raise ValueError("evidence must be an object")
    unknown = set(value) - set(EVIDENCE_FIELDS)
    if unknown:
        raise ValueError("evidence contains non-whitelisted fields")
    projected = {
        "source_release": _safe_id(value.get("source_release"), "evidence.source_release"),
        "measured_at": _safe_id(value.get("measured_at"), "evidence.measured_at"),
        "freshness": _enum(value.get("freshness"), _FRESHNESS, "evidence.freshness"),
        "scope": _enum(value.get("scope"), _EVIDENCE_SCOPE, "evidence.scope"),
        "acceptance_status": _enum(
            value.get("acceptance_status"), _ACCEPTANCE, "evidence.acceptance_status"
        ),
    }
    return projected


def _recovery_reason(facts: Mapping[str, Any]) -> str:
    if facts["main_status"] == "MAIN_RED":
        return "main_red"
    if facts["permission_status"] == "missing":
        return "missing_permission"
    if facts["scheduler_status"] == "failed":
        return "scheduler_failure"
    if facts["workflow_status"] == "failed":
        return "workflow_failure"
    if facts["recovery_status"] == "history_unsafe":
        return "history_unsafe"
    if facts["recovery_status"] == "expired_unreclaimed":
        return "expired_ownership"
    if facts["recovery_status"] == "reclaimed":
        return "reclaimed_ownership"
    return ""


def project_operator_state(
    facts: Mapping[str, Any],
    *,
    project_config: Mapping[str, Any],
    installation_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the strict Phase-2A operator projection for normalized facts."""
    if not isinstance(facts, Mapping):
        raise ValueError("facts must be an object")
    unknown = set(facts) - _ALLOWED_FACTS
    if unknown:
        raise ValueError("facts contain non-whitelisted fields")
    validate_persisted_input(facts)

    normalized = {
        "main_status": _enum(facts.get("main_status"), _MAIN, "main_status"),
        "scheduler_status": _enum(
            facts.get("scheduler_status"), _HEALTH, "scheduler_status"
        ),
        "workflow_status": _enum(facts.get("workflow_status"), _HEALTH, "workflow_status"),
        "permission_status": _enum(
            facts.get("permission_status"), _PERMISSION, "permission_status"
        ),
        "recovery_status": _enum(
            facts.get("recovery_status", ""), _RECOVERY, "recovery_status"
        ),
        "intentional_idle": _bool(facts.get("intentional_idle"), "intentional_idle"),
        "work_in_progress": _bool(
            facts.get("work_in_progress"), "work_in_progress"
        ),
        "review_needed": _bool(facts.get("review_needed"), "review_needed"),
        "completed_accepted": _bool(
            facts.get("completed_accepted"), "completed_accepted"
        ),
    }
    if normalized["completed_accepted"] and (
        normalized["work_in_progress"] or normalized["review_needed"]
    ):
        raise ValueError("completed state conflicts with active/review state")

    human, missing_human = _project_human_required(facts.get("human_required"))
    evidence = _project_evidence(facts.get("evidence"))
    recovery_reason = _recovery_reason(normalized)

    if human is not None:
        state = "human_required"
        reason = human.get("reason", "human_required_incomplete")
        action = human.get("action", "complete_human_required_fields")
    elif recovery_reason:
        state = "recovery_needed"
        reason = recovery_reason
        action = {
            "main_red": "repair_and_revalidate_main",
            "missing_permission": "restore_required_permission",
            "scheduler_failure": "repair_scheduler",
            "workflow_failure": "repair_workflow",
            "history_unsafe": "route_human_required_new_canonical_history",
            "expired_ownership": "reclaim_after_github_artifact_discovery",
            "reclaimed_ownership": "verify_reclaimed_work_and_continue",
        }[recovery_reason]
    elif normalized["review_needed"]:
        state, reason, action = (
            "review_needed",
            "exact_head_review_required",
            "route_current_head_to_independent_review",
        )
    elif normalized["work_in_progress"]:
        state, reason, action = (
            "work_in_progress",
            "canonical_work_active",
            "continue_canonical_next_action",
        )
    elif normalized["completed_accepted"]:
        state, reason, action = (
            "completed_accepted",
            "accepted_completion",
            "refresh_acceptance_evidence" if evidence["freshness"] != "current" else "none",
        )
    elif (
        normalized["intentional_idle"]
        and normalized["main_status"] == "MAIN_GREEN"
        and normalized["scheduler_status"] == "healthy"
        and normalized["workflow_status"] == "healthy"
        and normalized["permission_status"] == "ok"
    ):
        state, reason, action = ("healthy_idle", "intentional_idle", "none")
    else:
        state, reason, action = (
            "recovery_needed",
            "healthy_idle_not_proven",
            "inspect_scheduler_workflow_permissions_and_main",
        )

    profile = _validate_profile(project_config)
    installation = _project_installation(installation_state)
    installed_release = _safe_id(
        facts.get("installed_release_id"), "installed_release_id"
    )
    available_release = _safe_id(
        facts.get("available_release_id"), "available_release_id"
    )
    last_accepted = _safe_id(
        facts.get("last_accepted_release_id"), "last_accepted_release_id"
    )

    result = {
        "schema": "ai-bb-operator-projection:v1",
        "operator_state": state,
        "operator_reason": _text(reason, "operator_reason"),
        "operator_action": _text(action, "operator_action"),
        "profile": profile,
        "installation": installation,
        "release": {
            "installed_release_id": installed_release,
            "available_release_id": available_release,
            "upgrade_available": bool(
                installed_release and available_release and installed_release != available_release
            ),
            "last_accepted_release_id": last_accepted,
        },
        "evidence": evidence,
        "recovery_status": normalized["recovery_status"],
        "human_required": human,
        "human_required_complete": human is not None and not missing_human,
        "human_required_missing_fields": missing_human,
    }
    if result["operator_state"] not in OPERATOR_STATES:
        raise AssertionError("invalid derived operator state")
    return result
