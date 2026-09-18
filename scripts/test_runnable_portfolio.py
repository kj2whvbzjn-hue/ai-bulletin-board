#!/usr/bin/env python3
from runnable_portfolio import choose_runnable


def item(i, kind="implementation", **kw):
    return {"id": i, "kind": kind, "admitted": True, **kw}


# A claimed primary lane does not force idle when standing admitted work exists.
r = choose_runnable([item(115, claimed_by_other=True), item(97, "gap_scan")])
assert r["action"] == "RUN" and r["item"]["id"] == 97

# Local browser mismatch routes the browser lane while another safe lane runs.
r = choose_runnable([
    item(114, "acceptance", required_capabilities=["rendered_browser"]),
    item(97, "gap_scan"),
])
assert r["action"] == "RUN" and r["item"]["id"] == 97 and r["routed"][0]["id"] == 114

# If only capability-specific work remains, routing is required rather than IDLE.
r = choose_runnable([item(114, "acceptance", required_capabilities=["rendered_browser"])])
assert r["action"] == "ROUTE_REQUIRED"

# A capable executor receives the same admitted acceptance lane.
r = choose_runnable(
    [item(114, "acceptance", required_capabilities=["rendered_browser"])],
    ["rendered_browser"],
)
assert r["action"] == "RUN" and r["item"]["id"] == 114

# Priority is deterministic and review/integration outrank spare discovery.
r = choose_runnable([item(97, "gap_scan"), item(200, "review"), item(201, "integration")])
assert r["item"]["id"] == 200

# Security and MAIN_RED remediation retain scheduler priority over ordinary work.
r = choose_runnable([item(97, "gap_scan"), item(20, "main_red"), item(10, "security")])
assert r["action"] == "RUN" and r["item"]["id"] == 10
r = choose_runnable([item(97, "gap_scan"), item(20, "main_red")])
assert r["action"] == "RUN" and r["item"]["id"] == 20

# history_unsafe fails closed before unrelated runnable or routable work.
r = choose_runnable([
    item(115, history_unsafe=True),
    item(97, "gap_scan"),
    item(114, "acceptance", required_capabilities=["rendered_browser"]),
])
assert r["action"] == "STOP" and r["reason"] == "history_unsafe" and r["item"]["id"] == 115

# Explicit safety/Human Required stops are fail-closed, never evidence-free IDLE.
r = choose_runnable([item(115, safety_stop=True), item(97, "gap_scan")])
assert r["action"] == "STOP" and r["reason"] == "safety_stop"
r = choose_runnable([item(115, human_required=True), item(97, "gap_scan")])
assert r["action"] == "STOP" and r["reason"] == "human_required"

# Stop precedence is deterministic when multiple fail-closed gates are present.
r = choose_runnable([
    item(30, human_required=True),
    item(20, safety_stop=True),
    item(10, history_unsafe=True),
])
assert r["action"] == "STOP" and r["reason"] == "history_unsafe" and r["item"]["id"] == 10

# IDLE is allowed only after no safe admitted runnable/routable item or stop remains.
r = choose_runnable([{"id": 1, "kind": "audit", "admitted": False}])
assert r["action"] == "IDLE"

print("RUNNABLE_PORTFOLIO_OK")
