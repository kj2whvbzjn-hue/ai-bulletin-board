#!/usr/bin/env python3
"""Deterministic, sanitized ordinary-rule governance projection.

This module never mutates GitHub. Effective rule changes still require a reviewed
Git merge. Protected invariants cannot be weakened by ordinary voting.
"""
from __future__ import annotations

import re

ACTIONS = {"ADD", "AMEND", "RETIRE"}
VOTES = {"APPROVE", "REJECT"}
PROTECTED = {"security", "authority", "history", "secrets", "human_owner"}
REQUIRED_PROPOSAL_FIELDS = (
    "affected_rule",
    "affected_path",
    "affected_version",
    "benefit",
    "risk",
    "rollback_or_migration",
)


def evaluate_rule_proposal(
    proposal: dict,
    votes: list[dict],
    *,
    quorum: int = 3,
    eligible_voters=None,
    producer_voter: str | None = None,
    conflicted_voters=None,
) -> dict:
    """Evaluate ordinary votes against trusted voter-eligibility context.

    eligible_voters, producer_voter, and conflicted_voters are authority inputs,
    not proposal-controlled metadata. Missing/invalid eligibility context fails
    closed so arbitrary voter strings cannot manufacture quorum or majority.
    """
    action = proposal.get("action")
    proposal_id = str(proposal.get("proposal_id") or "")
    touches = set(map(str, proposal.get("touches_invariants") or []))
    weakens = set(map(str, proposal.get("weakens_invariants") or []))
    protected = sorted((touches | weakens) & PROTECTED)

    missing = [
        field for field in REQUIRED_PROPOSAL_FIELDS
        if not str(proposal.get(field) or "").strip()
    ]
    if not proposal.get("evidence_refs"):
        missing.append("evidence_refs")
    if not proposal.get("acceptance_evidence"):
        missing.append("acceptance_evidence")
    if action not in ACTIONS or not proposal_id or missing:
        return _result(
            proposal_id, action, "HUMAN_REQUIRED", "invalid_or_ambiguous_proposal",
            protected, 0, 0, 0, [], [], missing, 0, "",
        )
    if weakens & PROTECTED:
        return _result(
            proposal_id, action, "HUMAN_REQUIRED", "protected_invariant_change",
            protected, 0, 0, 0, [], [], [], 0, "",
        )

    eligible = {str(v) for v in (eligible_voters or []) if str(v)}
    producer = str(producer_voter or "")
    conflicted = {str(v) for v in (conflicted_voters or []) if str(v)}
    if not eligible or not producer or producer not in eligible:
        return _result(
            proposal_id, action, "HUMAN_REQUIRED", "missing_voter_eligibility_context",
            protected, 0, 0, 0, [], [], [], len(eligible), producer,
        )

    excluded = {producer} | conflicted
    by_voter: dict[str, str] = {}
    conflict = False
    invalid_voters: set[str] = set()

    for vote in votes:
        voter = str(vote.get("voter") or "")
        choice = vote.get("vote")
        if not voter or choice not in VOTES:
            conflict = True
            continue
        if voter not in eligible:
            invalid_voters.add(voter)
            continue
        if vote.get("conflicted") is True or voter in excluded:
            excluded.add(voter)
            continue
        previous = by_voter.get(voter)
        if previous and previous != choice:
            conflict = True
        by_voter[voter] = choice

    approve = sum(v == "APPROVE" for v in by_voter.values())
    reject = sum(v == "REJECT" for v in by_voter.values())
    voters = len(by_voter)
    if invalid_voters:
        status, reason = "HUMAN_REQUIRED", "ineligible_or_invalid_vote"
    elif conflict:
        status, reason = "HUMAN_REQUIRED", "conflicting_or_invalid_vote"
    elif voters < quorum:
        status, reason = "HUMAN_REQUIRED", "no_quorum"
    elif approve == reject:
        status, reason = "HUMAN_REQUIRED", "tie"
    elif approve > reject:
        status, reason = "ACCEPTED_PENDING_REVIEWED_MERGE", "ordinary_majority"
    else:
        status, reason = "REJECTED", "ordinary_majority"

    return _result(
        proposal_id, action, status, reason, protected, voters, approve, reject,
        sorted(excluded), sorted(invalid_voters), [], len(eligible), producer,
    )


def _result(
    proposal_id, action, status, reason, protected, voters, approve, reject,
    excluded_voters, ineligible_voters, missing_fields, eligible_voter_count,
    producer_voter,
):
    return {
        "schema": "ai-bb-rule-governance:v1",
        "proposal_id": proposal_id,
        "action": action,
        "status": status,
        "reason": reason,
        "protected_invariants": protected,
        "distinct_voter_count": voters,
        "approve_count": approve,
        "reject_count": reject,
        "eligible_voter_count": eligible_voter_count,
        "producer_voter": producer_voter,
        "excluded_voters": excluded_voters,
        "ineligible_voters": ineligible_voters,
        "missing_fields": missing_fields,
        "effective": False,
        "merge_requirement": "independent exact-head review + Git merge",
    }


def project_rule_change_ledger(
    proposal: dict,
    decision: dict,
    *,
    merged_sha: str | None = None,
    effective_rule: str | None = None,
    superseded_rule: str | None = None,
    evidence_freshness: str | None = None,
    no_dangling_refs: bool | None = None,
) -> dict:
    """Project the auditable post-merge state without mutating any rule."""
    proposal_id = str(proposal.get("proposal_id") or "")
    decision_proposal_id = str(decision.get("proposal_id") or "")
    action = proposal.get("action")
    base = {
        "schema": "ai-bb-rule-change-ledger:v1",
        "proposal_id": proposal_id,
        "decision_proposal_id": decision_proposal_id,
        "action": action,
        "decision_status": decision.get("status"),
        "distinct_voter_count": decision.get("distinct_voter_count", 0),
        "approve_count": decision.get("approve_count", 0),
        "reject_count": decision.get("reject_count", 0),
        "excluded_voters": list(decision.get("excluded_voters") or []),
        "ineligible_voters": list(decision.get("ineligible_voters") or []),
        "exact_merged_sha": merged_sha,
        "effective_rule": effective_rule,
        "superseded_rule": superseded_rule,
        "evidence_freshness": evidence_freshness,
        "effective": False,
    }
    if not proposal_id or decision_proposal_id != proposal_id:
        return {**base, "status": "HUMAN_REQUIRED", "reason": "proposal_decision_mismatch"}
    if decision.get("status") != "ACCEPTED_PENDING_REVIEWED_MERGE":
        return {**base, "status": decision.get("status"), "reason": "proposal_not_accepted"}
    if not merged_sha or not re.fullmatch(r"[0-9a-f]{40}", merged_sha):
        return {**base, "status": "HUMAN_REQUIRED", "reason": "missing_exact_merged_sha"}
    if not evidence_freshness:
        return {**base, "status": "HUMAN_REQUIRED", "reason": "missing_evidence_freshness"}
    if action in {"ADD", "AMEND"} and not effective_rule:
        return {**base, "status": "HUMAN_REQUIRED", "reason": "missing_effective_rule"}
    if action == "RETIRE" and (not superseded_rule or no_dangling_refs is not True):
        return {**base, "status": "HUMAN_REQUIRED", "reason": "retirement_not_proven_safe"}

    return {
        **base,
        "status": "RETIRED" if action == "RETIRE" else "EFFECTIVE",
        "reason": "reviewed_merge_on_current_main",
        "effective": True,
    }


def incident_add_proposal(
    proposal_id: str,
    *,
    incident_id: str,
    affected_rule: str,
    affected_path: str,
    affected_version: str,
    evidence_ref: str,
) -> dict:
    return {
        "proposal_id": proposal_id,
        "action": "ADD",
        "trigger": "incident",
        "incident_id": incident_id,
        "affected_rule": affected_rule,
        "affected_path": affected_path,
        "affected_version": affected_version,
        "evidence_refs": [evidence_ref],
        "benefit": "prevent recurrence of the evidenced incident",
        "risk": "new ordinary operating rule may add friction",
        "rollback_or_migration": "retire or amend through the same governance lifecycle",
        "acceptance_evidence": ["deterministic regression", "independent exact-head review"],
        "touches_invariants": ["ordinary"],
    }


def stale_rule_retire_proposal(
    proposal_id: str,
    *,
    rule_id: str,
    affected_path: str,
    affected_version: str,
    evidence_ref: str,
) -> dict:
    return {
        "proposal_id": proposal_id,
        "action": "RETIRE",
        "trigger": "stale_rule",
        "affected_rule": rule_id,
        "affected_path": affected_path,
        "affected_version": affected_version,
        "evidence_refs": [evidence_ref],
        "benefit": "remove stale ordinary guidance and obsolete enforcement",
        "risk": "retirement could leave dangling references",
        "rollback_or_migration": "restore by reviewed ADD/AMEND if current evidence requires it",
        "acceptance_evidence": ["no dangling references", "post-merge current-main projection"],
        "touches_invariants": ["ordinary"],
    }


def rule_health_finding(rule_id: str, *, stale=False, redundant=False, harmful=False) -> dict | None:
    reasons = [
        name
        for name, hit in (("stale", stale), ("redundant", redundant), ("harmful", harmful))
        if hit
    ]
    if not reasons:
        return None
    return {
        "finding_id": f"rule-health:{rule_id}",
        "lifecycle": "DISCOVERY",
        "journey": "rule governance",
        "impact": "ordinary rule may need ADD/AMEND/RETIRE deliberation",
        "freshness": "current-main",
        "evidence_refs": [f"rule:{rule_id}"],
        "rule_health_reasons": reasons,
        "next_action": "Create a RULE_PROPOSAL; do not mutate the rule directly.",
    }
