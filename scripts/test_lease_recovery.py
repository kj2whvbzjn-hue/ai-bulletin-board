#!/usr/bin/env python3
"""Deterministic regressions for repository-local safe-reclaim decisions."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("lease_recovery", Path(__file__).with_name("lease_recovery.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

MAIN = "a" * 40
HEAD = "b" * 40
STALE = "c" * 40

def snap(*candidates, complete=True, current_main=MAIN):
    return {
        "discovery_complete": complete,
        "current_main": current_main,
        "candidates": list(candidates),
    }

def candidate(ref="branch:recovered@bbbbbbb", head=HEAD, base=MAIN, scope=True):
    return {"ref": ref, "head_sha": head, "base_sha": base, "scope_match": scope}

# Incomplete discovery is fail-closed and requires a human decision.
out = m.decide_recovery(snap(complete=False))
assert out["route"] == "human_required"
assert out["action"] is None
assert out["reason"] == "incomplete GitHub discovery"

# No prior GitHub-native artifact means deterministic fresh restart.
out = m.decide_recovery(snap())
assert out["route"] == "autonomous"
assert out["action"] == "FRESH-RESTART"
assert out["head_sha"] == ""

# One scope-matching exact-base artifact can resume from its frozen SHA.
out = m.decide_recovery(snap(candidate()))
assert out["route"] == "autonomous"
assert out["action"] == "RESUME-EXACT"
assert out["head_sha"] == HEAD
assert out["frozen_ref"] == "branch:recovered@bbbbbbb"

# A stale/diverged base is synchronized rather than silently treated as exact.
out = m.decide_recovery(snap(candidate(base=STALE)))
assert out["route"] == "autonomous"
assert out["action"] == "SYNCHRONIZE"
assert out["head_sha"] == HEAD

# Out-of-scope recovered work is preserved as evidence but abandoned.
out = m.decide_recovery(snap(candidate(scope=False)))
assert out["route"] == "autonomous"
assert out["action"] == "ABANDON"
assert out["head_sha"] == HEAD

# Multiple plausible heads are ambiguous and must not be auto-selected.
out = m.decide_recovery(
    snap(
        candidate(ref="PR:#101@bbbbbbb"),
        candidate(ref="PR:#102@ccccccc", head=STALE),
    )
)
assert out["route"] == "human_required"
assert out["action"] is None
assert out["reason"] == "multiple candidate heads require explicit disambiguation"

# Invalid discovery evidence fails closed.
for bad in (
    {"discovery_complete": True, "current_main": "not-a-sha", "candidates": []},
    {"discovery_complete": True, "current_main": MAIN, "candidates": [{"ref": "bad ref"}]},
):
    try:
        m.decide_recovery(bad)
    except m.RecoveryDecisionError:
        pass
    else:
        raise AssertionError("invalid recovery evidence must fail closed")

print("lease_recovery regressions: ok")
