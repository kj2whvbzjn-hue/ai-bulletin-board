#!/usr/bin/env python3
"""Deterministic Product/UX/E2E evidence-to-action terminal gate.

Input/output is deliberately sanitized. This module does not fetch or mutate GitHub.
Canonical admission/ownership remains in GitHub Issues/comments; the gate only proves
that a material product event cannot be projected as terminal until reporting and
action-disposition receipts exist.
"""
from __future__ import annotations

MATERIAL_EVENTS = {
    "rendered_e2e_completion",
    "rendered_e2e_regression",
    "ux_finding_changed",
    "proposal_transition",
    "human_required",
    "main_red_recovery",
    "release_main_validation",
    "evidence_stale_missing",
}
ACCEPTANCE_CLASSES = {"VERIFIED", "PARTIAL", "MISSING", "EVIDENCE_MISSING"}
ACTION_KINDS = {"fresh_workstream", "live_equivalent", "DEFERRED", "REJECTED", "HUMAN_REQUIRED"}

def project_material_event(event: dict) -> dict:
    """Return a whitelisted operator receipt + action state for one material event."""
    kind = event.get("event_kind")
    if kind not in MATERIAL_EVENTS:
        return {"material": False, "terminal_ready": True}

    receipt = event.get("operator_report") or {}
    report_ready = all(receipt.get(k) for k in (
        "what_changed", "evidence_identity", "user_visible_impact", "next_action"
    )) and "unresolved_findings" in receipt

    acceptance = event.get("acceptance_class")
    disposition = event.get("action_disposition") or {}
    action_ready = (
        acceptance in ACCEPTANCE_CLASSES
        and disposition.get("kind") in ACTION_KINDS
        and bool(disposition.get("reason"))
    )
    if disposition.get("kind") in {"DEFERRED", "REJECTED"}:
        action_ready = action_ready and bool(disposition.get("authority"))
    if disposition.get("kind") in {"fresh_workstream", "live_equivalent"}:
        action_ready = action_ready and bool(disposition.get("workstream"))

    unresolved = list(receipt.get("unresolved_findings") or [])
    return {
        "material": True,
        "event_kind": kind,
        "evidence_identity": receipt.get("evidence_identity", ""),
        "acceptance_class": acceptance if acceptance in ACCEPTANCE_CLASSES else "EVIDENCE_MISSING",
        "operator_report_ready": bool(report_ready),
        "action_disposition_ready": bool(action_ready),
        "unresolved_finding_count": len(unresolved),
        "terminal_ready": bool(report_ready and action_ready),
        "next_action": receipt.get("next_action", ""),
    }

def terminal_projection(events: list[dict]) -> dict:
    projected = [project_material_event(e) for e in events]
    blocked = [p for p in projected if p.get("material") and not p.get("terminal_ready")]
    return {
        "schema": "ai-bb-evidence-action:v1",
        "material_event_count": sum(1 for p in projected if p.get("material")),
        "terminal_ready": not blocked,
        "blocked_material_event_count": len(blocked),
        "operator_report_required": any(not p.get("operator_report_ready", True) for p in blocked),
        "action_disposition_required": any(not p.get("action_disposition_ready", True) for p in blocked),
        "events": projected,
    }
