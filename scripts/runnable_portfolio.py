#!/usr/bin/env python3
"""Deterministic selection of admitted work before an IDLE decision."""

PRIORITY = {
    "security": 0,
    "main_red": 1,
    "live_claim": 2,
    "review": 3,
    "integration": 4,
    "implementation": 5,
    "acceptance": 6,
    "gap_scan": 7,
    "audit": 7,
}
STOP_PRIORITY = {
    "history_unsafe": 0,
    "safety_stop": 1,
    "human_required": 2,
}


def _stop_reason(item):
    if item.get("history_unsafe") or item.get("kind") == "history_unsafe":
        return "history_unsafe"
    if item.get("safety_stop"):
        return "safety_stop"
    if item.get("human_required"):
        return "human_required"
    return None


def choose_runnable(items, capabilities=()):
    capabilities = set(capabilities)
    runnable, routed, stops = [], [], []
    for item in items:
        if not item.get("admitted") or item.get("overlap"):
            continue
        stop_reason = _stop_reason(item)
        if stop_reason:
            stops.append((STOP_PRIORITY[stop_reason], item.get("id", 0), stop_reason, item))
            continue
        if item.get("claimed_by_other") or item.get("dependency_wait") or item.get("review_wait"):
            continue
        required = set(item.get("required_capabilities", ()))
        if not required.issubset(capabilities):
            routed.append(item)
            continue
        runnable.append(item)

    if stops:
        _, _, reason, item = min(stops, key=lambda row: (row[0], row[1]))
        return {"action": "STOP", "reason": reason, "item": item, "routed": routed}
    if runnable:
        runnable.sort(key=lambda item: (PRIORITY.get(item.get("kind"), 99), item.get("id", 0)))
        return {"action": "RUN", "item": runnable[0], "routed": routed}
    if routed:
        return {"action": "ROUTE_REQUIRED", "routed": routed}
    return {"action": "IDLE"}
