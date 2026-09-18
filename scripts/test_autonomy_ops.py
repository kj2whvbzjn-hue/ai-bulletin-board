#!/usr/bin/env python3
"""Deterministic regressions for v0.3 autonomy/watchdog derivation."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("autonomy", Path(__file__).with_name("autonomy_ops.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def row(task="#1", state="open", lease="", review=False, head="", next_action="work"):
    return {
        "task": task, "state": state, "agent": "", "lease_status": lease,
        "review_needed": review, "current_head": head, "next_action": next_action,
    }


# Duplicate dispatch/workstream must be a first-class health violation.
out = m.derive([row()], [], "MAIN_GREEN", {"v0.3/autonomy-ops": [59, 60]})
assert out["health"]["duplicate_workstream_violation"] is True

# Same exact SHA reviewed by more than one logical reviewer is a review storm.
reviews = [{"pr": 12, "head": "PR:#12@abcdef1", "review_needed": False, "review_count": 2, "stale_review_count": 0}]
out = m.derive([row(head="PR:#12@abcdef1")], reviews, "MAIN_GREEN", {})
assert out["health"]["review_storm"] is True

# Stale SHA review is surfaced and does not satisfy current-head work.
reviews = [{"pr": 12, "head": "PR:#12@abcdef2", "review_needed": True, "review_count": 0, "stale_review_count": 1}]
out = m.derive([row(head="PR:#12@abcdef2", review=True)], reviews, "MAIN_GREEN", {})
assert out["health"]["stale_review"] is True
assert out["queue"][0]["next_class"] == "review-needed"

# Red main freezes ordinary implementation/integration behind broken-main/security.
out = m.derive([row(task="#9"), row(task="#10", head="PR:#10@abcdef1")], [], "MAIN_RED", {})
assert all(x["next_class"] == "broken-main/security" for x in out["queue"])

# Lease expiry/reclaim availability remains visible: stale open task is implementation-ready.
out = m.derive([row(task="#11", state="open", lease="stale")], [], "MAIN_GREEN", {})
assert out["health"]["stale_or_expiring_claim"] is True
assert out["queue"][0]["next_class"] == "implementation-ready"

# Human-required escalation outranks otherwise implementation-ready state.
out = m.derive([row(task="#23", next_action="Human Owner must decide repository visibility")], [], "MAIN_GREEN", {})
assert out["health"]["human_required"] is True
assert out["queue"][0]["next_class"] == "idle/human-required"

# Completed tasks use the idle scheduling class but must not raise Human Required health.
completed = row(task="#24", state="completed")
completed["recovery_status"] = "completed"
out = m.derive([completed], [], "MAIN_GREEN", {})
assert out["queue"][0]["next_class"] == "idle/human-required"
assert out["queue"][0]["waiting_reason"] == "completed"
assert out["health"]["human_required"] is False

# Repeated expiry/reclaim churn is deterministic Human Required even without prose keywords.
churn = row(task="#25", state="open", lease="stale")
churn["recovery_status"] = "expired_unreclaimed"
churn["reclaim_count"] = 2
out = m.derive([churn], [], "MAIN_GREEN", {})
assert out["queue"][0]["next_class"] == "idle/human-required"
assert out["queue"][0]["waiting_reason"] == "repeated lease reclaim churn"
assert out["health"]["human_required"] is True

# history_unsafe remains a Human Required safety condition even though it routes through broken-main/security.
unsafe = row(task="#26", state="history_unsafe")
unsafe["recovery_status"] = "history_unsafe"
out = m.derive([unsafe], [], "MAIN_GREEN", {})
assert out["queue"][0]["next_class"] == "broken-main/security"
assert out["health"]["history_unsafe"] is True
assert out["health"]["human_required"] is True

# Main status is conservative: unknown without checks; red on any failure; green only all-complete safe conclusions.
assert m.main_check_state([]) == "MAIN_UNKNOWN"
assert m.main_check_state([{"status": "completed", "conclusion": "failure"}]) == "MAIN_RED"
assert m.main_check_state([
    {"status": "completed", "conclusion": "success"},
    {"status": "completed", "conclusion": "skipped"},
]) == "MAIN_GREEN"

# Current-main watchdog runs can deterministically self-report the validated
# default-branch SHA after preceding validation steps finish. PR/other SHAs
# must fall back to actual watchdog check evidence instead.
assert m.current_main_state("mainsha", [], "mainsha", "success") == "MAIN_GREEN"
assert m.current_main_state("mainsha", [], "mainsha", "failure") == "MAIN_RED"
assert m.current_main_state("mainsha", [], "othersha", "success") == "MAIN_UNKNOWN"
assert m.current_main_state(
    "mainsha",
    [{"status": "completed", "conclusion": "success"}],
    "othersha",
    "success",
) == "MAIN_GREEN"



def proto_event(typ, agent, task, key, artifacts, next_action="work", summary="event"):
    import json
    payload = {
        "type": typ, "agent_id": agent, "task": task, "idempotency_key": key,
        "summary": summary, "next_action": None if typ == "RESULT" else next_action,
        "artifacts": artifacts,
    }
    return "<!-- ai-bb:v1 -->\n```json\n" + json.dumps(payload) + "\n```"


def comment(cid, when, body, updated=None):
    return {"id": cid, "created_at": when, "updated_at": updated or when, "body": body}


HEAD1 = "PR:#61@abcdef1"
HEAD2 = "PR:#61@abcdef2"
base_comments = [
    comment(1, "2026-09-18T00:00:00Z", proto_event("CLAIM", "author", "#59", "claim", [])),
    comment(2, "2026-09-18T00:00:01Z", proto_event("PROGRESS", "author", "#59", "produce-h1", [HEAD1])),
]

# Producer self-review is not independent evidence.
comments = base_comments + [
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "author", "#59", "self-review", [HEAD1])),
]
assert m.review_evidence(comments, HEAD1, 59) == (0, 0)

# Malformed and task-mismatched REVIEW payloads do not count.
malformed = "<!-- ai-bb:v1 -->\n```json\n{\"type\":\"REVIEW\",\"agent_id\":\"reviewer\",\"task\":\"#59\",\"artifacts\":[\"PR:#61@abcdef1\"]}\n```"
comments = base_comments + [
    comment(3, "2026-09-18T00:00:02Z", malformed),
    comment(4, "2026-09-18T00:00:03Z", proto_event("REVIEW", "reviewer", "#60", "wrong-task", [HEAD1])),
]
assert m.review_evidence(comments, HEAD1, 59) == (0, 0)

# Any edited marker-bearing protocol comment fails review evidence closed.
comments = base_comments + [
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "reviewer", "#59", "edited-review", [HEAD1]),
            updated="2026-09-18T00:00:03Z"),
]
assert m.review_evidence(comments, HEAD1, 59) == (0, 0)

# Two genuine different logical reviewers on the exact produced head are a storm signal input.
comments = base_comments + [
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "reviewer-a", "#59", "review-a", [HEAD1])),
    comment(4, "2026-09-18T00:00:03Z", proto_event("REVIEW", "reviewer-b", "#59", "review-b", [HEAD1])),
]
assert m.review_evidence(comments, HEAD1, 59) == (2, 0)

# Stale-head independent review stays stale and never covers the current produced head.
comments = base_comments + [
    comment(3, "2026-09-18T00:00:02Z", proto_event("PROGRESS", "author", "#59", "produce-h2", [HEAD2])),
    comment(4, "2026-09-18T00:00:03Z", proto_event("REVIEW", "reviewer", "#59", "stale-review", [HEAD1])),
]
assert m.review_evidence(comments, HEAD2, 59) == (0, 1)

# Producer/reviewer attribution is stable across equivalent short/full SHA artifacts.
FULL1 = "abcdef1111111111111111111111111111111111"
full_h1 = f"PR:#61@{FULL1}"
short_h1 = "PR:#61@abcdef1"
comments = [
    comment(1, "2026-09-18T00:00:00Z", proto_event("CLAIM", "author", "#59", "claim-full-short", [])),
    comment(2, "2026-09-18T00:00:01Z", proto_event("PROGRESS", "author", "#59", "produce-full", [full_h1])),
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "reviewer", "#59", "review-short", [short_h1])),
]
assert m.review_evidence(comments, full_h1, 59) == (1, 0)
comments = [
    comment(1, "2026-09-18T00:00:00Z", proto_event("CLAIM", "author", "#59", "claim-short-full", [])),
    comment(2, "2026-09-18T00:00:01Z", proto_event("PROGRESS", "author", "#59", "produce-short", [short_h1])),
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "reviewer", "#59", "review-full", [full_h1])),
]
assert m.review_evidence(comments, full_h1, 59) == (1, 0)
comments = [
    comment(1, "2026-09-18T00:00:00Z", proto_event("CLAIM", "author", "#59", "claim-self-prefix", [])),
    comment(2, "2026-09-18T00:00:01Z", proto_event("PROGRESS", "author", "#59", "produce-self-full", [full_h1])),
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "author", "#59", "self-short", [short_h1])),
]
assert m.review_evidence(comments, full_h1, 59) == (0, 0)

# Review Queue is keyed to the actual current PR SHA, never a reviewed stale canonical head.
H1_FULL = "abcdef1111111111111111111111111111111111"
H2_FULL = "abcdef2222222222222222222222222222222222"
h1_short = "PR:#61@abcdef1"
h2_short = "PR:#61@abcdef2"
comments = [
    comment(1, "2026-09-18T00:00:00Z", proto_event("CLAIM", "author", "#59", "claim-exact", [])),
    comment(2, "2026-09-18T00:00:01Z", proto_event("PROGRESS", "author", "#59", "produce-old", [h1_short])),
    comment(3, "2026-09-18T00:00:02Z", proto_event("REVIEW", "reviewer-a", "#59", "review-old", [h1_short])),
]
stale_row = row(task="#59", review=False, head=h1_short)
entry = m.review_queue_entry(stale_row, comments, H2_FULL)
assert entry["head"] == f"PR:#61@{H2_FULL}"
assert entry["review_needed"] is True
assert entry["review_count"] == 0
assert entry["stale_review_count"] == 1
m.reconcile_task_review(stale_row, entry)
queue_out = m.derive([stale_row], [entry], "MAIN_GREEN", {})
assert queue_out["queue"][0]["current_head"] == f"PR:#61@{H2_FULL}"
assert queue_out["queue"][0]["review_needed"] is True
assert queue_out["queue"][0]["next_class"] == "review-needed"

# Once the actual current head has canonical producer + independent review evidence, coverage clears.
comments += [
    comment(4, "2026-09-18T00:00:03Z", proto_event("PROGRESS", "author", "#59", "produce-new", [h2_short])),
    comment(5, "2026-09-18T00:00:04Z", proto_event("REVIEW", "reviewer-b", "#59", "review-new", [h2_short])),
]
entry = m.review_queue_entry(stale_row, comments, H2_FULL)
assert entry["head"] == f"PR:#61@{H2_FULL}"
assert entry["review_needed"] is False
assert entry["review_count"] == 1
assert entry["stale_review_count"] == 1
covered_row = row(task="#59", review=True, head=h1_short)
m.reconcile_task_review(covered_row, entry)
queue_out = m.derive([covered_row], [entry], "MAIN_GREEN", {})
assert queue_out["queue"][0]["current_head"] == f"PR:#61@{H2_FULL}"
assert queue_out["queue"][0]["review_needed"] is False
assert queue_out["queue"][0]["next_class"] == "integration/verification"

print("autonomy_ops regressions: ok")
