#!/usr/bin/env python3
"""Pure safe-reclaim decision helper for repository-local recovery.

This module is deliberately non-authoritative: GitHub canonical replay decides
ownership. The helper classifies already-discovered GitHub-native candidate
artifacts after a winning post-expiry CLAIM/replay and before any mutation.
"""

from __future__ import annotations

import re

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
REF_RE = re.compile(r"^[A-Za-z0-9._:/#@+\-]+$")


class RecoveryDecisionError(ValueError):
    pass


def _candidate(candidate):
    if not isinstance(candidate, dict):
        raise RecoveryDecisionError("candidate must be an object")
    ref = str(candidate.get("ref") or "")
    head_sha = str(candidate.get("head_sha") or "")
    base_sha = str(candidate.get("base_sha") or "")
    if not ref or REF_RE.fullmatch(ref) is None:
        raise RecoveryDecisionError("candidate ref must be a safe immutable reference")
    if SHA_RE.fullmatch(head_sha) is None:
        raise RecoveryDecisionError("candidate head_sha must be an immutable SHA")
    if SHA_RE.fullmatch(base_sha) is None:
        raise RecoveryDecisionError("candidate base_sha must be an immutable SHA")
    scope_match = candidate.get("scope_match")
    if not isinstance(scope_match, bool):
        raise RecoveryDecisionError("candidate scope_match must be boolean")
    return {
        "ref": ref,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "scope_match": scope_match,
    }


def decide_recovery(snapshot):
    """Classify a completed discovery snapshot without mutating repository state.

    Return keys:
      route: autonomous | human_required
      action: RESUME-EXACT | SYNCHRONIZE | ABANDON | FRESH-RESTART | None
      reason: stable operator-facing reason
      frozen_ref/head_sha: immutable continuation evidence when applicable
    """
    if not isinstance(snapshot, dict):
        raise RecoveryDecisionError("snapshot must be an object")
    complete = snapshot.get("discovery_complete")
    if not isinstance(complete, bool):
        raise RecoveryDecisionError("discovery_complete must be boolean")
    current_main = str(snapshot.get("current_main") or "")
    if SHA_RE.fullmatch(current_main) is None:
        raise RecoveryDecisionError("current_main must be an immutable SHA")
    raw_candidates = snapshot.get("candidates")
    if not isinstance(raw_candidates, list):
        raise RecoveryDecisionError("candidates must be a list")
    candidates = [_candidate(item) for item in raw_candidates]

    if not complete:
        return {
            "route": "human_required",
            "action": None,
            "reason": "incomplete GitHub discovery",
            "frozen_ref": "",
            "head_sha": "",
        }
    if not candidates:
        return {
            "route": "autonomous",
            "action": "FRESH-RESTART",
            "reason": "no prior GitHub-native candidate artifacts",
            "frozen_ref": "",
            "head_sha": "",
        }
    if len(candidates) > 1:
        return {
            "route": "human_required",
            "action": None,
            "reason": "multiple candidate heads require explicit disambiguation",
            "frozen_ref": "",
            "head_sha": "",
        }

    candidate = candidates[0]
    if not candidate["scope_match"]:
        return {
            "route": "autonomous",
            "action": "ABANDON",
            "reason": "candidate does not match admitted workstream scope",
            "frozen_ref": candidate["ref"],
            "head_sha": candidate["head_sha"],
        }
    if candidate["base_sha"] == current_main:
        return {
            "route": "autonomous",
            "action": "RESUME-EXACT",
            "reason": "single scope-matching candidate is based on exact current main",
            "frozen_ref": candidate["ref"],
            "head_sha": candidate["head_sha"],
        }
    return {
        "route": "autonomous",
        "action": "SYNCHRONIZE",
        "reason": "single scope-matching candidate is stale or diverged from current main",
        "frozen_ref": candidate["ref"],
        "head_sha": candidate["head_sha"],
    }
