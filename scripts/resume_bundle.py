#!/usr/bin/env python3
"""Build a bounded, non-authoritative resume working-set projection.

Inputs are already-retrieved GitHub-native facts. This helper only shapes
worker-private ephemeral context; it never reads or mutates canonical state.
"""
from __future__ import annotations

from datetime import datetime, timezone

SCHEMA = "ai-bb-resume-bundle:v1"
RULE_KEYS = ("worker_bootstrap", "ai_instructions", "github_protocol")
ISSUE_KEYS = (
    "number", "title", "state", "workstream", "owner", "next_gate",
    "history_unsafe",
)
PR_KEYS = (
    "number", "head_sha", "base_sha", "mergeable", "checks", "review_state",
    "next_gate",
)


def _iso(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _pick(source, keys):
    return {key: source.get(key) for key in keys}


def build_resume_bundle(
    *,
    main_sha,
    rule_refs,
    owner_manager_directive_ref,
    review_directive_ref=None,
    review_relevant=False,
    active_issues=(),
    open_prs=(),
    next_gates=(),
    target_issue=None,
    resolved_history=(),
    generated_at,
):
    """Return the minimum sufficient ordinary-resume working set.

    resolved_history is counted only. Its payload is deliberately excluded.
    target_issue is the only place full canonical replay inputs may appear,
    and callers must keep the resulting bundle worker-private and ephemeral.
    """
    if not main_sha:
        raise ValueError("main_sha is required")
    missing = [key for key in RULE_KEYS if not rule_refs.get(key)]
    if missing:
        raise ValueError(f"missing canonical rule refs: {','.join(missing)}")

    issues = sorted(
        (_pick(item, ISSUE_KEYS) for item in active_issues),
        key=lambda item: int(item.get("number") or 0),
    )
    prs = sorted(
        (_pick(item, PR_KEYS) for item in open_prs),
        key=lambda item: int(item.get("number") or 0),
    )

    target = None
    if target_issue is not None:
        target = {
            "number": target_issue.get("number"),
            "issue_body": target_issue.get("issue_body"),
            "canonical_events": list(target_issue.get("canonical_events") or []),
            "history_unsafe": bool(target_issue.get("history_unsafe")),
        }

    stamp = _iso(generated_at)
    return {
        "schema": SCHEMA,
        "authoritative": False,
        "visibility": "worker-private-ephemeral",
        "source_of_truth": "GitHub Issue/comments + immutable refs",
        "main_sha": str(main_sha),
        "freshness": {"generated_at": stamp, "main_sha": str(main_sha)},
        "rule_refs": {key: str(rule_refs[key]) for key in RULE_KEYS},
        "directive_refs": {
            "owner_manager": owner_manager_directive_ref,
            "review": review_directive_ref if review_relevant else None,
        },
        "active_queue": {
            "issues": issues,
            "prs": prs,
            "next_gates": list(next_gates),
        },
        "target_replay": target,
        "omitted_history": {
            "count": len(tuple(resolved_history)),
            "policy": "on-demand-only",
        },
    }
