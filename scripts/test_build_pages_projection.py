#!/usr/bin/env python3
"""Deterministic regression tests for the Pages canonical replay."""
from datetime import datetime, timedelta, timezone
import copy
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("projection", Path(__file__).with_name("build_pages_projection.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

def iso(t):
    return t.isoformat().replace("+00:00", "Z")

def comment(cid, seconds, payload, edited=False):
    created = T0 + timedelta(seconds=seconds)
    body = m.MARKER + "\n\x60\x60\x60json\n" + __import__("json").dumps(payload) + "\n\x60\x60\x60"
    return {"id": cid, "created_at": iso(created), "updated_at": iso(created + timedelta(seconds=1) if edited else created), "body": body}

def event(kind, agent, key, next_action="work"):
    return {"type": kind, "agent_id": agent, "task": "#1", "idempotency_key": key, "summary": kind, "next_action": None if kind == "RESULT" else next_action, "artifacts": []}

issue = {"number": 1}

# Edited marker-bearing comment must fail closed even when current body is malformed.
bad = comment(1, 0, event("CLAIM", "a", "k1"), edited=True)
bad["body"] = m.MARKER + "\nnot-json"
assert m.replay(issue, [bad], T0)[0] == "history_unsafe"

# Expired former owner cannot renew or complete after the 900-second boundary.
comments = [
    comment(1, 0, event("CLAIM", "a", "k1")),
    comment(2, 901, event("HEARTBEAT", "a", "k2")),
    comment(3, 902, event("RESULT", "a", "k3")),
]
state, owner, _ = m.replay(issue, comments, T0 + timedelta(seconds=903))
assert (state, owner) == ("open", None)

# A later claimant after expiry owns; old owner RELEASE cannot clear it.
comments.append(comment(4, 903, event("CLAIM", "b", "k4")))
comments.append(comment(5, 904, event("RELEASE", "a", "k5")))
state, owner, _ = m.replay(issue, comments, T0 + timedelta(seconds=905))
assert (state, owner) == ("claimed", "b")

# Conflicting duplicate idempotency key has no state effect.
comments = [
    comment(1, 0, event("CLAIM", "a", "same")),
    comment(2, 1, event("RELEASE", "a", "same")),
]
state, owner, _ = m.replay(issue, comments, T0 + timedelta(seconds=2))
assert (state, owner) == ("claimed", "a")

# Effective RESULT remains terminal to later protocol CLAIMs in this Issue.
comments = [
    comment(1, 0, event("CLAIM", "a", "r1")),
    comment(2, 1, event("RESULT", "a", "r2")),
    comment(3, 2, event("CLAIM", "b", "r3")),
]
state, owner, _ = m.replay(issue, comments, T0 + timedelta(seconds=3))
assert (state, owner) == ("completed", None)

# Projection boundary is an explicit whitelist and never copies Issue/comment payloads.
privacy_claim = event("CLAIM", "agent-safe", "privacy-claim")
secret = event("PROGRESS", "agent-safe", "privacy-1", "Authorization: Bearer super-secret-token-value")
secret["artifacts"] = ["PR:#53@97e0d877", "https://evil.example/raw", "token=secret"]
c = comment(9, 1, secret)
state, owner, last = m.replay(issue, [comment(8, 0, privacy_claim), c], T0 + timedelta(seconds=2))
row = m.project_row({"number": 1, "title": "Authorization: Bearer title-secret", "body": "RAW PRIVATE ISSUE BODY"}, state, owner, last)
assert tuple(row.keys()) == m.SAFE_FIELDS
assert row["title"] == "[redacted]"
assert row["next_action"] == "[redacted]"
assert row["artifacts"] == ["PR:#53@97e0d877"]
assert row["last_activity_at"] == iso(T0 + timedelta(seconds=1))
assert row["lease_expires_at"] == iso(T0 + timedelta(seconds=900))
assert row["review_needed"] is True
assert row["current_head"] == "PR:#53@97e0d877"
serialized = __import__("json").dumps(row)
assert "RAW PRIVATE ISSUE BODY" not in serialized
assert "super-secret-token-value" not in serialized
assert "title-secret" not in serialized
assert "evil.example" not in serialized
assert "token=secret" not in serialized

# Exact-head REVIEW coverage clears review_needed without exposing review bodies.
reviewed = event("REVIEW", "reviewer", "privacy-2", "checked")
reviewed["artifacts"] = ["PR:#53@97e0d877"]
state, owner, last = m.replay(issue, [comment(8, 0, privacy_claim), c, comment(10, 2, reviewed)], T0 + timedelta(seconds=3))
row = m.project_row({"number": 1, "title": "Safe title"}, state, owner, last)
assert row["review_needed"] is False
assert row["current_head"] == "PR:#53@97e0d877"
assert row["last_activity_at"] == iso(T0 + timedelta(seconds=2))

# Stale lease evidence survives later non-ownership activity after expiry.
stale_claim = event("CLAIM", "lease-owner", "lease-1")
stale_review = event("REVIEW", "reviewer", "lease-2")
state, owner, last = m.replay(
    issue,
    [comment(20, 0, stale_claim), comment(21, 901, stale_review)],
    T0 + timedelta(seconds=902),
)
row = m.project_row({"number": 1, "title": "Lease task"}, state, owner, last)
assert (state, owner) == ("open", None)
assert row["lease_expires_at"] == iso(T0 + timedelta(seconds=900))
assert row["lease_status"] == "stale"
assert row["recovery_status"] == "expired_unreclaimed"
assert row["prior_owner"] == "lease-owner"
assert row["prior_claim_ref"] == "comment:20"
assert row["prior_lease_expires_at"] == iso(T0 + timedelta(seconds=900))
assert row["claim_ref"] == ""
assert row["last_owner_activity_at"] == iso(T0)
assert row["reclaim_count"] == 0
assert row["next_action"].startswith("Fresh-CLAIM/replay")

# Exact expiry is fail-closed; a heartbeat at the boundary cannot renew.
boundary_comments = [
    comment(22, 0, event("CLAIM", "boundary-owner", "boundary-claim")),
    comment(23, 900, event("HEARTBEAT", "boundary-owner", "boundary-heartbeat")),
]
state, owner, last = m.replay(issue, boundary_comments, T0 + timedelta(seconds=901))
boundary_row = m.project_row({"number": 1, "title": "Boundary task"}, state, owner, last)
assert (state, owner) == ("open", None)
assert boundary_row["recovery_status"] == "expired_unreclaimed"
assert boundary_row["prior_owner"] == "boundary-owner"
assert boundary_row["last_owner_activity_at"] == iso(T0)

# A heartbeat before expiry extends the lease without changing protocol semantics.
before_comments = [
    comment(24, 0, event("CLAIM", "live-owner", "live-claim")),
    comment(25, 899, event("HEARTBEAT", "live-owner", "live-heartbeat")),
]
state, owner, last = m.replay(issue, before_comments, T0 + timedelta(seconds=900))
before_row = m.project_row({"number": 1, "title": "Live task"}, state, owner, last)
assert (state, owner) == ("claimed", "live-owner")
assert before_row["recovery_status"] == "active"
assert before_row["claim_ref"] == "comment:24"
assert before_row["lease_started_at"] == iso(T0)
assert before_row["lease_expires_at"] == iso(T0 + timedelta(seconds=1799))
assert before_row["last_owner_activity_at"] == iso(T0 + timedelta(seconds=899))

# First post-expiry CLAIM becomes the only live owner, retains prior-owner audit,
# and losing/late former-worker events cannot masquerade as active owner activity.
reclaim_b = event("CLAIM", "reclaimer", "reclaim-b", "continue exact recovered SHA")
losing_c = event("CLAIM", "loser", "reclaim-c", "wrong claimant action")
late_old = event("PROGRESS", "lease-owner", "late-old", "late old worker action")
late_old["artifacts"] = ["PR:#53@3333333"]
reclaim_comments = [
    comment(26, 0, event("CLAIM", "lease-owner", "reclaim-origin")),
    comment(27, 901, reclaim_b),
    comment(28, 902, losing_c),
    comment(29, 903, late_old),
]
state, owner, last = m.replay(issue, reclaim_comments, T0 + timedelta(seconds=904))
reclaim_row = m.project_row({"number": 1, "title": "Reclaimed task"}, state, owner, last)
assert (state, owner) == ("claimed", "reclaimer")
assert reclaim_row["recovery_status"] == "reclaimed"
assert reclaim_row["prior_owner"] == "lease-owner"
assert reclaim_row["prior_claim_ref"] == "comment:26"
assert reclaim_row["reclaim_ref"] == "comment:27"
assert reclaim_row["reclaim_at"] == iso(T0 + timedelta(seconds=901))
assert reclaim_row["reclaim_count"] == 1
assert reclaim_row["last_owner_activity_at"] == iso(T0 + timedelta(seconds=901))
assert reclaim_row["next_action"] == "continue exact recovered SHA"
assert reclaim_row["current_head"] == ""

# A voluntary RELEASE after one reclaim ends that recovery cycle. A later normal
# CLAIM is active, not a second reclaim, while prior expiry remains audit evidence.
released_after_reclaim = event("RELEASE", "reclaimer", "reclaim-release", "released cleanly")
fresh_after_release = event("CLAIM", "fresh-owner", "fresh-after-release", "new ordinary work")
release_cycle_comments = reclaim_comments[:2] + [
    comment(30, 904, released_after_reclaim),
    comment(31, 905, fresh_after_release),
]
state, owner, last = m.replay(issue, release_cycle_comments, T0 + timedelta(seconds=906))
release_cycle_row = m.project_row({"number": 1, "title": "Post-release claim"}, state, owner, last)
assert (state, owner) == ("claimed", "fresh-owner")
assert release_cycle_row["recovery_status"] == "active"
assert release_cycle_row["reclaim_count"] == 1
assert release_cycle_row["prior_owner"] == "lease-owner"
assert release_cycle_row["reclaim_ref"] == "comment:27"
assert release_cycle_row["claim_ref"] == "comment:31"

# Released/completed/history_unsafe remain distinct non-authoritative diagnostics.
state, owner, last = m.replay(
    issue,
    [comment(80, 0, event("CLAIM", "a", "release-claim")), comment(81, 1, event("RELEASE", "a", "release-event"))],
    T0 + timedelta(seconds=2),
)
assert m.project_row({"number": 1, "title": "Released"}, state, owner, last)["recovery_status"] == "released"
state, owner, last = m.replay(
    issue,
    [comment(82, 0, event("CLAIM", "a", "result-claim")), comment(83, 1, event("RESULT", "a", "result-event"))],
    T0 + timedelta(seconds=2),
)
assert m.project_row({"number": 1, "title": "Completed"}, state, owner, last)["recovery_status"] == "completed"
unsafe_row = m.project_row({"number": 1, "title": "Unsafe"}, "history_unsafe", None, None)
assert unsafe_row["recovery_status"] == "history_unsafe"
assert "Human Owner" in unsafe_row["next_action"]

# Review coverage is exact-head and must come from a different logical agent.
head1 = "PR:#53@1111111"
head2 = "PR:#53@2222222"
owner_claim = event("CLAIM", "author", "head-claim")
produced1 = event("PROGRESS", "author", "head-1")
produced1["artifacts"] = [head1]
produced2 = event("PROGRESS", "author", "head-2")
produced2["artifacts"] = [head2]
stale_review = event("REVIEW", "reviewer", "head-review-old")
stale_review["artifacts"] = [head1]
state, owner, last = m.replay(
    issue,
    [comment(30, 0, owner_claim), comment(31, 1, produced1), comment(32, 2, produced2), comment(33, 3, stale_review)],
    T0 + timedelta(seconds=4),
)
row = m.project_row({"number": 1, "title": "Review task"}, state, owner, last)
assert row["current_head"] == head2
assert row["review_needed"] is True

# A later non-review mention of an already-seen older head must not regress current_head.
stale_nonreview = event("PROGRESS", "manager", "head-stale-nonreview")
stale_nonreview["artifacts"] = [head1]
state, owner, last = m.replay(
    issue,
    [comment(40, 0, owner_claim), comment(41, 1, produced1), comment(42, 2, produced2), comment(43, 3, stale_nonreview)],
    T0 + timedelta(seconds=4),
)
row = m.project_row({"number": 1, "title": "Non-regressive head task"}, state, owner, last)
assert row["current_head"] == head2
assert row["review_needed"] is True

self_review = event("REVIEW", "author", "head-self-review")
self_review["artifacts"] = [head1]
state, owner, last = m.replay(
    issue,
    [comment(50, 0, owner_claim), comment(51, 1, produced1), comment(52, 2, self_review)],
    T0 + timedelta(seconds=3),
)
row = m.project_row({"number": 1, "title": "Self review task"}, state, owner, last)
assert row["review_needed"] is True

# A non-owner mention cannot establish or overwrite implementation-head authorship.
manager_mention = event("PROGRESS", "manager", "head-manager-mention")
manager_mention["artifacts"] = [head1]
author_review = event("REVIEW", "author", "head-author-review")
author_review["artifacts"] = [head1]
state, owner, last = m.replay(
    issue,
    [comment(60, 0, owner_claim), comment(61, 1, manager_mention), comment(62, 2, produced1), comment(63, 3, author_review)],
    T0 + timedelta(seconds=4),
)
row = m.project_row({"number": 1, "title": "Author attribution task"}, state, owner, last)
assert row["current_head"] == head1
assert row["review_needed"] is True

independent_review = event("REVIEW", "other-reviewer", "head-independent-review")
independent_review["artifacts"] = [head1]
state, owner, last = m.replay(
    issue,
    [comment(70, 0, owner_claim), comment(71, 1, manager_mention), comment(72, 2, produced1), comment(73, 3, independent_review)],
    T0 + timedelta(seconds=4),
)
row = m.project_row({"number": 1, "title": "Independent review task"}, state, owner, last)
assert row["current_head"] == head1
assert row["review_needed"] is False

# Benign display strings are bounded and normalized.
assert m.safe_text("  review   PR #53  ") == "review PR #53"
assert len(m.safe_text("x" * 500)) == 280

# v0.3 autonomy projection: exact whitelisted fields, Human Required extraction,
# and conservative exact-head dedupe when legacy task references disagree.
autonomy = {
    "schema": "ai-bb-autonomy:v1",
    "generated": True,
    "health": {
        "main_status": "MAIN_GREEN",
        "duplicate_workstream_violation": False,
        "review_storm": True,
        "stale_review": True,
        "stale_or_expiring_claim": False,
        "history_unsafe": False,
        "human_required": True,
        "raw_private": "must not project",
    },
    "queue": [
        {
            "task": "#23",
            "state": "open",
            "agent": "",
            "lease_status": "",
            "review_needed": False,
            "current_head": "",
            "next_action": "Human Owner must decide account setting",
            "next_class": "idle/human-required",
            "waiting_reason": "human-required decision",
            "raw_comment": "PRIVATE",
        },
        {
            "task": "#59",
            "state": "open",
            "agent": "",
            "lease_status": "stale",
            "review_needed": True,
            "current_head": "PR:#68@d33e02d",
            "next_action": "Review exact head",
            "next_class": "review-needed",
            "waiting_reason": "current exact head lacks independent review",
        },
    ],
    "review_queue": [
        {"pr": 68, "head": "PR:#68@d33e02d", "review_needed": False, "review_count": 1, "stale_review_count": 0},
        {"pr": 68, "head": "PR:#68@d33e02d", "review_needed": True, "review_count": 0, "stale_review_count": 2},
    ],
    "duplicate_workstreams": {},
}
a = m.project_autonomy(autonomy, "kj2whvbzjn-hue/ai-bulletin-board")
assert tuple(a["health"]) == m.AUTONOMY_HEALTH_FIELDS
assert "raw_private" not in a["health"]
assert len(a["review_queue"]) == 1
assert a["review_queue"][0] == {
    "repository": "kj2whvbzjn-hue/ai-bulletin-board",
    "pr": 68,
    "head": "PR:#68@d33e02d",
    "review_needed": True,
    "review_count": 0,
    "stale_review_count": 2,
}
assert a["human_required"] == [{
    "task": "#23",
    "next_action": "Human Owner must decide account setting",
    "waiting_reason": "human-required decision",
}]

# Deterministic recovery/safety Human Required conditions must survive the
# sanitized projection even when they use non-generic scheduler classes/reasons.
recovery_autonomy = copy.deepcopy(autonomy)
recovery_autonomy["queue"].extend([
    {
        "task": "#60",
        "state": "open",
        "agent": "",
        "lease_status": "stale",
        "recovery_status": "expired_unreclaimed",
        "reclaim_count": 2,
        "review_needed": False,
        "current_head": "",
        "next_action": "Human Owner must inspect repeated lease reclaim churn.",
        "next_class": "idle/human-required",
        "waiting_reason": "repeated lease reclaim churn",
    },
    {
        "task": "#61",
        "state": "history_unsafe",
        "agent": "",
        "lease_status": "",
        "recovery_status": "history_unsafe",
        "review_needed": False,
        "current_head": "",
        "next_action": "Human Owner must create a new canonical Issue.",
        "next_class": "broken-main/security",
        "waiting_reason": "history_unsafe",
    },
    {
        "task": "#62",
        "state": "completed",
        "agent": "",
        "lease_status": "",
        "recovery_status": "completed",
        "review_needed": False,
        "current_head": "",
        "next_action": "",
        "next_class": "idle/human-required",
        "waiting_reason": "completed",
    },
])
recovery_projection = m.project_autonomy(recovery_autonomy, "kj2whvbzjn-hue/ai-bulletin-board")
assert recovery_projection["human_required"] == [
    {
        "task": "#23",
        "next_action": "Human Owner must decide account setting",
        "waiting_reason": "human-required decision",
    },
    {
        "task": "#60",
        "next_action": "Human Owner must inspect repeated lease reclaim churn.",
        "waiting_reason": "repeated lease reclaim churn",
    },
    {
        "task": "#61",
        "next_action": "Human Owner must create a new canonical Issue.",
        "waiting_reason": "history_unsafe",
    },
]
assert all(row["task"] != "#62" for row in recovery_projection["human_required"])
assert "raw_comment" not in json.dumps(a)

bad_autonomy = copy.deepcopy(autonomy)
bad_autonomy["review_queue"][0]["head"] = "PR:#67@d33e02d"
try:
    m.project_autonomy(bad_autonomy, "kj2whvbzjn-hue/ai-bulletin-board")
except ValueError as exc:
    assert "match pr" in str(exc)
else:
    raise AssertionError("mismatched review PR/head must fail closed")

# Product/UX/E2E summaries are validated first and only whitelisted fields project.
metrics = {
    "transition_success": True,
    "destination_correct": True,
    "action_count": 2,
    "vertical_travel_px": 0,
    "vertical_travel_vh": 0,
    "reversal_count": 0,
    "target_visible_before": False,
    "target_visible_after": False,
    "target_distance_before_px": 147,
    "target_distance_after_px": 0,
    "horizontal_overflow_px": 0,
    "overlap_count": 0,
    "clipping_count": 2,
    "state_persistence_pass": True,
    "keyboard_accessibility_pass": True,
    "empty_error_state_pass": True,
}
proposal = {
    "schema_version": "ai-bb-product-ux-e2e:v1",
    "kind": "product_proposal",
    "proposal_id": "product/review-queue",
    "lifecycle": "PROPOSED",
    "problem": "Review work is hard to discover.",
    "evidence_refs": ["Issue:#59"],
    "expected_user_value": "Make exact-head waiting work visible.",
    "affected_surfaces": ["pages-board"],
    "dependencies": [],
    "security_privacy_constraints": ["sanitized-projection-only"],
    "acceptance_tests": ["review-queue-visible"],
    "size_risk": "small presentation follow-up",
    "owner": "product-lab",
    "next_action": "Request admission",
}
finding = {
    "schema_version": "ai-bb-product-ux-e2e:v1",
    "kind": "ux_finding",
    "finding_id": "ux/narrow-review-target",
    "lifecycle": "VERIFIED",
    "evidence_refs": ["artifact:rendered-e2e/review-target"],
    "surfaces": ["pages-board"],
    "friction": "Target is below the narrow viewport.",
    "hypothesis": "Reduce vertical chrome.",
    "acceptance_tests": ["desktop-narrow-rendered-pass"],
    "workstream_ref": "v0.3/autonomy-ops",
    "rendered_e2e_ref": "artifact:rendered-e2e/review-target-after",
    "owner": "ux-lab",
    "next_action": None,
}
baseline = {
    "schema_version": "ai-bb-product-ux-e2e:v1",
    "kind": "e2e_result",
    "journey_id": "board/review-needed-inspect",
    "executor_schema": "browser-agent-live-board-baseline:v1",
    "measured_at": "2026-09-18T01:00:00Z",
    "viewport": {"class": "narrow", "width": 390, "height": 844},
    "metrics": metrics,
    "artifact_ref": "artifact:baseline-review-narrow",
    "baseline_ref": None,
    "comparison": "baseline",
    "budgets": None,
    "next_action": "Compare future result",
}
compared = copy.deepcopy(baseline)
compared["measured_at"] = "2026-09-18T02:00:00Z"
compared["artifact_ref"] = "artifact:after-review-narrow"
compared["baseline_ref"] = baseline["artifact_ref"]
compared["comparison"] = "improved"
compared["metrics"] = dict(metrics, target_distance_before_px=20)
compared["budgets"] = {
    "baseline_ref": baseline["artifact_ref"],
    "rationale": "Measured baseline supports this target-distance ceiling.",
    "thresholds": {"target_distance_before_px": 147},
}
p = m.project_product_ux([proposal, finding, baseline, compared])
assert p["proposals"][0]["proposal_id"] == "product/review-queue"
assert p["ux_findings"][0]["visual_acceptance_status"] == "verified"
assert p["ux_findings"][0]["rendered_e2e_ref"] == "artifact:rendered-e2e/review-target-after"
assert len(p["e2e_latest"]) == 1
assert p["e2e_latest"][0]["artifact_ref"] == "artifact:after-review-narrow"
assert p["e2e_latest"][0]["baseline_ref"] == "artifact:baseline-review-narrow"
assert p["e2e_latest"][0]["comparison"] == "improved"
assert p["e2e_latest"][0]["budgets"]["thresholds"] == {"target_distance_before_px": 147}

unsafe = copy.deepcopy(proposal)
unsafe["evidence_refs"] = ["https://evil.example/raw?token=secret"]
try:
    m.project_product_ux([unsafe])
except ValueError:
    pass
else:
    raise AssertionError("URL/query evidence reference must not enter Pages projection")

# Complete v2 document is additive: existing tasks remain and new surfaces are bounded.
document = m.build_output(
    [row],
    autonomy,
    "kj2whvbzjn-hue/ai-bulletin-board",
    [proposal, finding, baseline, compared],
)
assert document["schema"] == "ai-bb-pages:v2"
assert set(document) == {"schema", "generated", "tasks", "autonomy", "product_ux"}
assert document["tasks"] == [row]
serialized = json.dumps(document)
for secret_text in ("RAW PRIVATE ISSUE BODY", "raw_private", "raw_comment", "evil.example"):
    assert secret_text not in serialized

print("pages projection replay/privacy/v0.3 schema regressions: ok")
