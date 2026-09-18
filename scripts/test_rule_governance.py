#!/usr/bin/env python3
from rule_governance import evaluate_rule_proposal, rule_health_finding

p={"proposal_id":"rp-1","action":"AMEND","touches_invariants":["ordinary"]}
votes=[{"voter":"a","vote":"APPROVE"},{"voter":"b","vote":"APPROVE"},{"voter":"c","vote":"REJECT"}]
out=evaluate_rule_proposal(p,votes)
assert out["status"]=="ACCEPTED_PENDING_REVIEWED_MERGE"
assert out["distinct_voter_count"]==3 and out["effective"] is False

assert evaluate_rule_proposal(p,votes[:2])["reason"]=="no_quorum"
tie=votes+[{"voter":"d","vote":"REJECT"}]
assert evaluate_rule_proposal(p,tie)["reason"]=="tie"
conflict=votes+[{"voter":"a","vote":"REJECT"}]
assert evaluate_rule_proposal(p,conflict)["reason"]=="conflicting_or_invalid_vote"

protected={"proposal_id":"rp-2","action":"RETIRE","weakens_invariants":["security"]}
assert evaluate_rule_proposal(protected,votes)["reason"]=="protected_invariant_change"

rejected=[{"voter":"a","vote":"REJECT"},{"voter":"b","vote":"REJECT"},{"voter":"c","vote":"APPROVE"}]
assert evaluate_rule_proposal(p,rejected)["status"]=="REJECTED"

finding=rule_health_finding("ordinary/example",stale=True,redundant=True)
assert finding["lifecycle"]=="DISCOVERY"
assert finding["rule_health_reasons"]==["stale","redundant"]
assert rule_health_finding("healthy") is None
print("RULE_GOVERNANCE_OK")
