#!/usr/bin/env python3
"""Derive a read-only autonomy/watchdog snapshot from GitHub-native state.

This tool never mutates Issues, PRs, repository settings, or protocol state.
It consumes canonical GitHub Issue/comment history plus exact current PR heads
and emits a small sanitized operational snapshot for Actions/Pages consumers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import build_pages_projection as projection

WORKSTREAM_RE = re.compile(r"(?mi)^workstream:\s*([a-z0-9._/-]+)\s*$")
HEAD_RE = re.compile(r"^PR:#?(\d+)@([0-9a-f]{7,40})$")
HUMAN_RE = re.compile(r"(?i)\b(?:human required|human owner|owner decision|required human)\b")
FAIL_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}

SAFE_TASK_FIELDS = (
    "task", "state", "agent", "lease_status", "recovery_status",
    "claim_ref", "lease_started_at", "prior_owner", "prior_claim_ref",
    "prior_lease_expires_at", "reclaim_ref", "reclaim_at",
    "last_owner_activity_at", "reclaim_count",
    "review_needed", "current_head", "next_action", "next_class", "waiting_reason",
)
SAFE_REVIEW_FIELDS = ("pr", "head", "review_needed", "review_count", "stale_review_count")
SAFE_HEALTH_FIELDS = (
    "main_status", "duplicate_workstream_violation", "review_storm",
    "stale_review", "stale_or_expiring_claim", "history_unsafe", "human_required",
)


def api(url: str):
    token = os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-bb-autonomy-watchdog",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


def paged(url: str):
    out = []
    page = 1
    while True:
        sep = "&" if "?" in url else "?"
        batch = api(f"{url}{sep}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise RuntimeError("unexpected GitHub response")
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def workstream_keys(issues):
    owners = defaultdict(list)
    for issue in issues:
        if "pull_request" in issue or issue.get("state") != "open":
            continue
        body = issue.get("body") or ""
        for key in WORKSTREAM_RE.findall(body):
            owners[key].append(issue["number"])
    return {k: sorted(v) for k, v in owners.items()}


def main_check_state(check_runs):
    if not check_runs:
        return "MAIN_UNKNOWN"
    if any((c.get("conclusion") or "") in FAIL_CONCLUSIONS for c in check_runs):
        return "MAIN_RED"
    completed = [c for c in check_runs if c.get("status") == "completed"]
    if len(completed) == len(check_runs) and all(
        (c.get("conclusion") or "") in {"success", "neutral", "skipped"} for c in completed
    ):
        return "MAIN_GREEN"
    return "MAIN_UNKNOWN"


def current_main_state(head_sha, check_runs, run_sha=None, validation_outcome=None):
    """Resolve main from the current watchdog run when it validates exact main.

    A PR run must never self-promote its branch/merge SHA to MAIN_GREEN. Outside
    a current-main watchdog run, only watchdog-named check evidence is used.
    """
    if run_sha == head_sha:
        if validation_outcome == "success":
            return "MAIN_GREEN"
        if validation_outcome == "failure":
            return "MAIN_RED"
    return main_check_state(check_runs)


def head_identity(artifact):
    m = HEAD_RE.fullmatch(artifact or "")
    return (int(m.group(1)), m.group(2)) if m else None


def same_head(artifact, target):
    """Match the same PR head while allowing canonical short SHA artifacts."""
    left = head_identity(artifact)
    right = head_identity(target)
    return bool(left and right and left[0] == right[0] and (left[1].startswith(right[1]) or right[1].startswith(left[1])))


def head_author(head_authors, head):
    """Resolve producer attribution across equivalent short/full SHA artifacts."""
    for produced_head, author in head_authors.items():
        if same_head(produced_head, head):
            return author
    return None


def review_evidence(comments, current_head, issue_number):
    """Count only canonical independent review evidence under replay semantics."""
    events = []
    for c in comments:
        body = c.get("body") or ""
        if projection.MARKER not in body:
            continue
        created = projection.parse_time(c["created_at"])
        updated = c.get("updated_at")
        if updated and projection.parse_time(updated) != created:
            return 0, 0
        p = projection.payload(body)
        if p is not None and projection.canonical(p, issue_number):
            events.append((created, int(c["id"]), p))
    events.sort(key=lambda x: (x[0], x[1]))

    seen = {}
    owner = None
    expiry = None
    completed = False
    head_authors = {}
    current_reviewers = set()
    stale_reviewers = set()

    for created, _cid, p in events:
        key = p["idempotency_key"]
        normalized = json.dumps(p, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen[key] = normalized

        if owner is not None and expiry is not None and created >= expiry:
            owner = None
            expiry = None
        live = owner is not None and expiry is not None
        typ = p["type"]
        heads = [x for x in p.get("artifacts", []) if HEAD_RE.fullmatch(x)]

        if typ == "REVIEW":
            for head in heads:
                author = head_author(head_authors, head)
                if not author or p["agent_id"] == author:
                    continue
                if same_head(head, current_head):
                    current_reviewers.add(p["agent_id"])
                else:
                    stale_reviewers.add(p["agent_id"])
        elif typ in {"PROGRESS", "HANDOFF", "RESULT"} and live and p["agent_id"] == owner:
            for head in heads:
                if head_author(head_authors, head) is None:
                    head_authors[head] = p["agent_id"]

        if typ == "CLAIM":
            if not live and not completed:
                owner = p["agent_id"]
                expiry = created + timedelta(seconds=projection.LEASE_SECONDS)
        elif typ == "HEARTBEAT":
            if live and p["agent_id"] == owner:
                expiry = created + timedelta(seconds=projection.LEASE_SECONDS)
        elif typ == "RELEASE":
            if live and p["agent_id"] == owner:
                owner = expiry = None
        elif typ == "RESULT":
            if live and p["agent_id"] == owner:
                completed = True
                owner = expiry = None

    return len(current_reviewers), len(stale_reviewers)


def review_queue_entry(row, comments, exact_head_sha):
    """Project review state against the actual current PR head, never a stale task ref."""
    head = row.get("current_head") or ""
    m = HEAD_RE.fullmatch(head)
    if not m:
        return None
    pr_number = int(m.group(1))
    issue_number = int(row["task"][1:])
    exact_head = f"PR:#{pr_number}@{exact_head_sha}" if exact_head_sha else head
    review_count, stale_count = review_evidence(comments, exact_head, issue_number)
    return {
        "pr": pr_number,
        "head": exact_head,
        "review_needed": review_count == 0,
        "review_count": review_count,
        "stale_review_count": stale_count,
    }


def reconcile_task_review(row, entry):
    """Apply exact current-PR review state before scheduler classification."""
    if not entry:
        return
    row["current_head"] = entry["head"]
    row["review_needed"] = bool(entry["review_needed"])


def classify_task(row, main_status):
    state = row.get("state") or "open"
    next_action = row.get("next_action") or ""
    recovery = row.get("recovery_status") or ""
    reclaim_count = int(row.get("reclaim_count") or 0)
    if state == "history_unsafe":
        return "broken-main/security", "history_unsafe"
    if HUMAN_RE.search(next_action):
        return "idle/human-required", "human-required decision"
    if main_status == "MAIN_RED":
        return "broken-main/security", "required current-main check is red"
    if state == "claimed":
        if recovery == "reclaimed":
            return "live-claim", "reclaimed after prior lease expiry"
        if recovery == "expiring":
            return "live-claim", "lease expiring"
        return "live-claim", row.get("lease_status") or "active claim"
    if recovery == "expired_unreclaimed":
        if reclaim_count >= 2:
            return "idle/human-required", "repeated lease reclaim churn"
        return "implementation-ready", "lease expired; autonomous safe reclaim available"
    if row.get("current_head") and row.get("review_needed"):
        return "review-needed", "current exact head lacks independent review"
    if row.get("current_head"):
        return "integration/verification", "reviewed current head awaits integration/verification"
    if state == "completed":
        return "idle/human-required", "completed"
    return "implementation-ready", "open and unclaimed"


def derive(tasks, review_meta, main_status, duplicate_keys):
    queue = []
    for row in tasks:
        next_class, reason = classify_task(row, main_status)
        safe = {k: row.get(k, "") for k in SAFE_TASK_FIELDS if k not in {"next_class", "waiting_reason"}}
        recovery = row.get("recovery_status") or ""
        reclaim_count = int(row.get("reclaim_count") or 0)
        if recovery == "expired_unreclaimed":
            if reclaim_count >= 2:
                safe["next_action"] = (
                    "Human Owner must inspect repeated lease reclaim churn and GitHub-native "
                    "candidate history before another reclaim."
                )
            else:
                safe["next_action"] = (
                    "Fresh-CLAIM/replay this task, then discover prior GitHub-native branches, "
                    "commits, open/closed PRs, checks, reviews, and artifacts before any mutation."
                )
        elif row.get("state") == "history_unsafe":
            safe["next_action"] = (
                "Human Owner must create a new canonical Issue; do not continue this history_unsafe task."
            )
        safe["next_class"] = next_class
        safe["waiting_reason"] = reason
        queue.append(safe)

    queue.sort(key=lambda x: ([
        "broken-main/security", "live-claim", "review-needed",
        "implementation-ready", "integration/verification", "idle/human-required"
    ].index(x["next_class"]), int((x.get("task") or "#0")[1:])))

    health = {
        "main_status": main_status,
        "duplicate_workstream_violation": bool(duplicate_keys),
        "review_storm": any(x["review_count"] > 1 for x in review_meta),
        "stale_review": any(x["stale_review_count"] > 0 for x in review_meta),
        "stale_or_expiring_claim": any(
            x.get("lease_status") in {"stale", "expiring"}
            or x.get("recovery_status") == "expired_unreclaimed"
            for x in tasks
        ),
        "history_unsafe": any(x.get("state") == "history_unsafe" for x in tasks),
        "human_required": any(
            x.get("waiting_reason") in {
                "human-required decision",
                "repeated lease reclaim churn",
                "history_unsafe",
            }
            for x in queue
        ),
    }
    return {
        "schema": "ai-bb-autonomy:v1",
        "generated": True,
        "health": {k: health[k] for k in SAFE_HEALTH_FIELDS},
        "queue": queue,
        "review_queue": review_meta,
        "duplicate_workstreams": duplicate_keys,
    }


def collect(repo: str):
    root = f"https://api.github.com/repos/{repo}"
    repository = api(root)
    main_sha = repository["default_branch"]
    branch = api(f"{root}/branches/{main_sha}")
    head_sha = branch["commit"]["sha"]

    issues = [x for x in paged(f"{root}/issues?state=all") if "pull_request" not in x]
    open_issues = [x for x in issues if x.get("state") == "open"]
    now = datetime.now(timezone.utc)

    tasks = []
    comments_by_issue = {}
    for issue in issues:
        comments = paged(issue["comments_url"])
        comments_by_issue[issue["number"]] = comments
        state, owner, last = projection.replay(issue, comments, now)
        tasks.append(projection.project_row(issue, state, owner, last))

    review_meta = []
    for row in tasks:
        head = row.get("current_head") or ""
        if not head:
            continue
        m = HEAD_RE.fullmatch(head)
        if not m:
            continue
        pr_number = int(m.group(1))
        issue_number = int(row["task"][1:])
        exact_head_sha = api(f"{root}/pulls/{pr_number}").get("head", {}).get("sha", "")
        entry = review_queue_entry(row, comments_by_issue[issue_number], exact_head_sha)
        if entry:
            reconcile_task_review(row, entry)
            review_meta.append(entry)
    review_meta = [{k: x[k] for k in SAFE_REVIEW_FIELDS} for x in review_meta]

    checks = api(
        f"{root}/commits/{head_sha}/check-runs"
        "?check_name=watchdog&filter=latest&per_page=100"
    ).get("check_runs", [])
    main_status = current_main_state(
        head_sha,
        checks,
        run_sha=os.environ.get("GITHUB_SHA"),
        validation_outcome=os.environ.get("AI_BB_MAIN_VALIDATION_OUTCOME"),
    )
    duplicates = {k: v for k, v in workstream_keys(open_issues).items() if len(v) > 1}
    return derive(tasks, review_meta, main_status, duplicates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="pages/autonomy.json")
    args = parser.parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("GITHUB_REPOSITORY is required")
    data = collect(repo)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
