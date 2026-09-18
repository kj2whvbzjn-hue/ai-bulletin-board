#!/usr/bin/env python3
"""Deterministic scheduler guard for repeated non-execution incidents.

Inputs must be sanitized canonical dispatch/outcome facts. This module does not
read private executor payloads or mutate GitHub.
"""
from __future__ import annotations

CAUSES = {
    "dispatch_not_consumed", "worker_ignored_instruction",
    "worker_local_capability_mismatch", "shared_executor_undiscovered",
    "shared_executor_unavailable", "executor_invocation_failed",
    "permission_human_required", "dependency_safety_gate", "scheduler_defect",
}
SAFETY_GATES = {"MAIN_RED", "history_unsafe", "HUMAN_REQUIRED", "security"}


def _executed(event: dict) -> bool:
    if event.get("safety_gate") in SAFETY_GATES:
        return True
    if event.get("execution_evidence"):
        return True
    if event.get("required_executor"):
        return bool(event.get("executor_attempt_evidence") or
                    event.get("executor_unavailable_evidence"))
    return False


def evaluate_repeated_non_execution(events: list[dict], *, proposed_dispatch: dict | None = None) -> dict:
    """Return scheduler action for one materially equivalent objective."""
    strikes = [e for e in events if not _executed(e)]
    strike_count = len(strikes)
    cause = next((str(e.get("cause")) for e in reversed(events)
                  if e.get("cause") in CAUSES), None)
    corrective = next((str(e.get("corrective_next_action")) for e in reversed(events)
                       if e.get("corrective_next_action")), None)

    if proposed_dispatch is not None and strike_count >= 2 and not (cause and corrective):
        return {
            "status": "REJECTED",
            "reason": "third_identical_dispatch_before_root_cause_classification",
            "strike_count": strike_count,
            "incident": "REPEATED_NON_EXECUTION",
            "cause": cause,
            "corrective_next_action": corrective,
        }
    if strike_count >= 2:
        return {
            "status": "ESCALATE",
            "reason": "second_materially_equivalent_non_execution",
            "strike_count": strike_count,
            "incident": "REPEATED_NON_EXECUTION",
            "cause": cause,
            "corrective_next_action": corrective,
        }
    if strike_count == 1:
        return {
            "status": "CORRECTIVE_REDISPATCH_ALLOWED",
            "reason": "first_non_execution",
            "strike_count": 1,
            "incident": None,
            "cause": cause,
            "corrective_next_action": corrective,
        }
    return {
        "status": "EXECUTED_OR_GATED",
        "reason": "no_non_execution_strike",
        "strike_count": 0,
        "incident": None,
        "cause": cause,
        "corrective_next_action": corrective,
    }
