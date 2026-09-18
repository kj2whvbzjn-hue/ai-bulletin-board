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
r = choose_runnable([item(114, "acceptance", required_capabilities=["rendered_browser"])], ["rendered_browser"])
assert r["action"] == "RUN" and r["item"]["id"] == 114

# Priority is deterministic and integration/review outrank spare discovery.
r = choose_runnable([item(97, "gap_scan"), item(200, "review"), item(201, "integration")])
assert r["item"]["id"] == 200

# IDLE is allowed only after no safe admitted runnable/routable item remains.
r = choose_runnable([{"id": 1, "kind": "audit", "admitted": False}])
assert r["action"] == "IDLE"

print("RUNNABLE_PORTFOLIO_OK")
