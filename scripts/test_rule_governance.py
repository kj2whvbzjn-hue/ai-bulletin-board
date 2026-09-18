#!/usr/bin/env python3
from rule_governance import (
    evaluate_rule_proposal,
    incident_add_proposal,
    project_rule_change_ledger,
    rule_health_finding,
    stale_rule_retire_proposal,
)

BASE = {
    "proposal_id": "rp-1",
    "action": "AMEND",
    "affected_rule": "ordinary/example",
    "affected_path": "AI_INSTRUCTIONS.md",
    "affected_version": "v1",
    "evidence_refs": ["incident:1"],
    "benefit": "reduce repeated manual correction",
    "risk": "could add unnecessary friction",
    "rollback_or_migration": "retire through reviewed governance",
    "acceptance_evidence": ["regression:test"],
    "touches_invariants": ["ordinary"],
}
votes = [
    {"voter": "a", "vote": "APPROVE"},
    {"voter": "b", "vote": "APPROVE"},
    {"voter": "c", "vote": "REJECT"},
]
out = evaluate_rule_proposal(BASE, votes)
assert out["status"] == "ACCEPTED_PENDING_REVIEWED_MERGE"
assert out["distinct_voter_count"] == 3 and out["effective"] is False

assert evaluate_rule_proposal(BASE, votes[:2])["reason"] == "no_quorum"
tie = votes + [{"voter": "d", "vote": "REJECT"}]
assert evaluate_rule_proposal(BASE, tie)["reason"] == "tie"
conflict = votes + [{"voter": "a", "vote": "REJECT"}]
assert evaluate_rule_proposal(BASE, conflict)["reason"] == "conflicting_or_invalid_vote"

protected = {**BASE, "proposal_id": "rp-2", "action": "RETIRE", "weakens_invariants": ["security"]}
assert evaluate_rule_proposal(protected, votes)["reason"] == "protected_invariant_change"

rejected = [
    {"voter": "a", "vote": "REJECT"},
    {"voter": "b", "vote": "REJECT"},
    {"voter": "c", "vote": "APPROVE"},
]
assert evaluate_rule_proposal(BASE, rejected)["status"] == "REJECTED"

# Producer/conflicted voters are excluded from quorum and majority.
excluded_proposal = {
    **BASE,
    "proposal_id": "rp-excluded",
    "producer_voter": "producer",
    "conflicted_voters": ["conflicted"],
}
excluded_votes = [
    {"voter": "producer", "vote": "APPROVE"},
    {"voter": "conflicted", "vote": "APPROVE"},
    {"voter": "a", "vote": "APPROVE"},
    {"voter": "b", "vote": "APPROVE"},
    {"voter": "c", "vote": "REJECT"},
]
excluded_out = evaluate_rule_proposal(excluded_proposal, excluded_votes)
assert excluded_out["status"] == "ACCEPTED_PENDING_REVIEWED_MERGE"
assert excluded_out["distinct_voter_count"] == 3
assert excluded_out["excluded_voters"] == ["conflicted", "producer"]

flagged_votes = votes + [{"voter": "d", "vote": "APPROVE", "conflicted": True}]
flagged_out = evaluate_rule_proposal(BASE, flagged_votes)
assert flagged_out["distinct_voter_count"] == 3
assert flagged_out["excluded_voters"] == ["d"]

# Proposal metadata is fail-closed rather than silently inferred.
malformed = {**BASE}
del malformed["acceptance_evidence"]
assert evaluate_rule_proposal(malformed, votes)["reason"] == "invalid_or_ambiguous_proposal"

# Incident-derived ADD demonstration.
incident_add = incident_add_proposal(
    "rp-incident-add",
    incident_id="incident-invalid-result-replay",
    affected_rule="worker-result-validation",
    affected_path="WORKER_BOOTSTRAP.md",
    affected_version="v2",
    evidence_ref="Issue:#16:5731425425",
)
incident_decision = evaluate_rule_proposal(incident_add, votes)
assert incident_add["action"] == "ADD" and incident_add["trigger"] == "incident"
assert incident_decision["status"] == "ACCEPTED_PENDING_REVIEWED_MERGE"

# Stale-rule RETIRE end-to-end demonstration, including no-dangling-ref gate.
finding = rule_health_finding("ordinary/obsolete", stale=True, redundant=True)
assert finding["lifecycle"] == "DISCOVERY"
retire = stale_rule_retire_proposal(
    "rp-retire",
    rule_id="ordinary/obsolete",
    affected_path="AI_INSTRUCTIONS.md",
    affected_version="v1",
    evidence_ref=finding["evidence_refs"][0],
)
retire_decision = evaluate_rule_proposal(retire, votes)
blocked_retire = project_rule_change_ledger(
    retire,
    retire_decision,
    merged_sha="1" * 40,
    superseded_rule="ordinary/obsolete@v1",
    evidence_freshness="current-main",
    no_dangling_refs=False,
)
assert blocked_retire["reason"] == "retirement_not_proven_safe"
retired = project_rule_change_ledger(
    retire,
    retire_decision,
    merged_sha="1" * 40,
    superseded_rule="ordinary/obsolete@v1",
    evidence_freshness="current-main",
    no_dangling_refs=True,
)
assert retired["status"] == "RETIRED" and retired["effective"] is True

# Post-merge effective-rule ledger requires exact immutable merge evidence.
ledger = project_rule_change_ledger(
    BASE,
    out,
    merged_sha="a" * 40,
    effective_rule="ordinary/example@v2",
    superseded_rule="ordinary/example@v1",
    evidence_freshness="current-main",
)
assert ledger["status"] == "EFFECTIVE" and ledger["effective"] is True
assert ledger["exact_merged_sha"] == "a" * 40
assert ledger["effective_rule"] == "ordinary/example@v2"
assert ledger["superseded_rule"] == "ordinary/example@v1"
assert ledger["evidence_freshness"] == "current-main"

missing_merge = project_rule_change_ledger(
    BASE,
    out,
    effective_rule="ordinary/example@v2",
    evidence_freshness="current-main",
)
assert missing_merge["reason"] == "missing_exact_merged_sha"

assert rule_health_finding("healthy") is None
print("RULE_GOVERNANCE_OK")
