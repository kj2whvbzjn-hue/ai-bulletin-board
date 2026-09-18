"""Reusable, tokenless Productization v1 Phase-1 core helpers.

This module deliberately performs no network I/O.  It consumes the frozen
Phase-0 installation/config vocabulary and returns deterministic values/plans
that a later GitHub adapter may execute.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic_identity(kind: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{kind}:sha256:{digest}"


@dataclass(frozen=True)
class PrincipalGrant:
    principal: str
    capabilities: frozenset[str]
    scopes: frozenset[str]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PrincipalGrant":
        return cls(
            principal=str(value["principal"]),
            capabilities=frozenset(map(str, value.get("capabilities", ()))),
            scopes=frozenset(map(str, value.get("scopes", ()))),
        )


def event_is_authorized(
    event: Mapping[str, Any],
    grants: Iterable[PrincipalGrant],
    *,
    capability: str,
    scope: str,
) -> bool:
    """Return whether an event may affect state for the requested operation.

    Display/audit retention is a caller concern; this function only decides
    state effect.  Identity is GitHub-native actor login supplied in the event.
    """
    actor = event.get("actor") or event.get("github_actor")
    if not isinstance(actor, str) or not actor:
        return False
    for grant in grants:
        if grant.principal != actor:
            continue
        if capability not in grant.capabilities:
            return False
        return "*" in grant.scopes or scope in grant.scopes
    return False


def package_manifest(
    installation: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    package_version: str = "1",
) -> dict[str, str]:
    """Build stable release identity without repository-specific literals."""
    installation_id = deterministic_identity("installation", installation)
    config_id = deterministic_identity("config", config)
    release_seed = {
        "package_version": package_version,
        "installation_id": installation_id,
        "config_id": config_id,
    }
    return {
        **release_seed,
        "release_id": deterministic_identity("release", release_seed),
    }


def plan_single_repo_reconcile(
    installation: Mapping[str, Any],
    config: Mapping[str, Any],
    observed_paths: Sequence[str],
) -> list[dict[str, str]]:
    """Return a deterministic offline plan; never executes GitHub mutations."""
    repo = installation.get("repository") or installation.get("repo")
    if not isinstance(repo, str) or not repo:
        raise ValueError("installation requires symbolic repository/repo")
    required = config.get("required_paths", ())
    if not isinstance(required, list) or not all(isinstance(p, str) and p for p in required):
        raise ValueError("config.required_paths must be a list of non-empty strings")
    observed = set(observed_paths)
    return [
        {"op": "ensure_path", "repository": repo, "path": path}
        for path in sorted(set(required))
        if path not in observed
    ]
