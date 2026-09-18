#!/usr/bin/env python3
"""Deterministic, sanitized ordinary-rule governance projection.

This module never mutates GitHub. Effective rule changes still require a reviewed
Git merge. Protected invariants cannot be weakened by ordinary voting.
"""
from __future__ import annotations

ACTIONS={"ADD","AMEND","RETIRE"}
VOTES={"APPROVE","REJECT"}
PROTECTED={"security","authority","history","secrets","human_owner"}

def evaluate_rule_proposal(proposal: dict, votes: list[dict], *, quorum: int = 3) -> dict:
    action=proposal.get("action")
    proposal_id=str(proposal.get("proposal_id") or "")
    touches=set(map(str, proposal.get("touches_invariants") or []))
    weakens=set(map(str, proposal.get("weakens_invariants") or []))
    protected=sorted((touches | weakens) & PROTECTED)
    if action not in ACTIONS or not proposal_id:
        return _result(proposal_id, action, "HUMAN_REQUIRED", "invalid_or_ambiguous_proposal", protected, 0, 0, 0)
    if protected and weakens & PROTECTED:
        return _result(proposal_id, action, "HUMAN_REQUIRED", "protected_invariant_change", protected, 0, 0, 0)

    by_voter={}
    conflict=False
    for vote in votes:
        voter=str(vote.get("voter") or "")
        choice=vote.get("vote")
        if not voter or choice not in VOTES:
            conflict=True
            continue
        previous=by_voter.get(voter)
        if previous and previous != choice:
            conflict=True
        by_voter[voter]=choice
    approve=sum(v=="APPROVE" for v in by_voter.values())
    reject=sum(v=="REJECT" for v in by_voter.values())
    voters=len(by_voter)
    if conflict:
        status,reason="HUMAN_REQUIRED","conflicting_or_invalid_vote"
    elif voters < quorum:
        status,reason="HUMAN_REQUIRED","no_quorum"
    elif approve == reject:
        status,reason="HUMAN_REQUIRED","tie"
    elif approve > reject:
        status,reason="ACCEPTED_PENDING_REVIEWED_MERGE","ordinary_majority"
    else:
        status,reason="REJECTED","ordinary_majority"
    return _result(proposal_id, action, status, reason, protected, voters, approve, reject)

def _result(proposal_id, action, status, reason, protected, voters, approve, reject):
    return {
        "schema":"ai-bb-rule-governance:v1",
        "proposal_id":proposal_id,
        "action":action,
        "status":status,
        "reason":reason,
        "protected_invariants":protected,
        "distinct_voter_count":voters,
        "approve_count":approve,
        "reject_count":reject,
        "effective":False,
        "merge_requirement":"independent exact-head review + Git merge",
    }

def rule_health_finding(rule_id: str, *, stale=False, redundant=False, harmful=False) -> dict | None:
    reasons=[name for name,hit in (("stale",stale),("redundant",redundant),("harmful",harmful)) if hit]
    if not reasons:
        return None
    return {
        "finding_id":f"rule-health:{rule_id}",
        "lifecycle":"DISCOVERY",
        "journey":"rule governance",
        "impact":"ordinary rule may need ADD/AMEND/RETIRE deliberation",
        "freshness":"current-main",
        "evidence_refs":[f"rule:{rule_id}"],
        "rule_health_reasons":reasons,
        "next_action":"Create a RULE_PROPOSAL; do not mutate the rule directly.",
    }
