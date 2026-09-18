#!/usr/bin/env python3
"""Deterministic selection of admitted work before an IDLE decision."""

PRIORITY = {"security": 0, "main_red": 1, "live_claim": 2, "review": 3, "integration": 4, "implementation": 5, "acceptance": 6, "gap_scan": 7, "audit": 7}

def choose_runnable(items, capabilities=()):
    capabilities = set(capabilities)
    runnable, routed = [], []
    for item in items:
        if not item.get("admitted") or item.get("overlap"):
            continue
        if item.get("claimed_by_other") or item.get("dependency_wait") or item.get("review_wait"):
            continue
        required = set(item.get("required_capabilities", ()))
        if not required.issubset(capabilities):
            routed.append(item)
            continue
        runnable.append(item)
    if runnable:
        runnable.sort(key=lambda item: (PRIORITY.get(item.get("kind"), 99), item.get("id", 0)))
        return {"action": "RUN", "item": runnable[0], "routed": routed}
    if routed:
        return {"action": "ROUTE_REQUIRED", "routed": routed}
    return {"action": "IDLE"}
