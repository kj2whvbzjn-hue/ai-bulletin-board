"""Reusable, tokenless Productization v1 Phase-1 core helpers."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

_SCOPE = re.compile(r"^(?:\*|role:[a-z][a-z0-9_-]*|workstream:[a-z0-9][a-z0-9._/-]*)$")
_SECRET_KEYS = ("secret", "token", "password", "private_key")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic_identity(kind: str, value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"{kind}:sha256:{digest}"


def validate_persisted_input(value: Any, path: str = "$") -> None:
    """Fail closed when a persisted input appears to contain secret material."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower()
            if any(marker in name for marker in _SECRET_KEYS) and not name.endswith(("_ref", "_name")):
                raise ValueError(f"secret value is not persistable at {path}.{key}")
            validate_persisted_input(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_persisted_input(item, f"{path}[{index}]")


@dataclass(frozen=True)
class PrincipalGrant:
    principal: str
    capabilities: frozenset[str]
    scopes: frozenset[str]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PrincipalGrant":
        scopes = frozenset(map(str, value.get("scopes", value.get("task_scope", ()))))
        if not scopes or any(not _SCOPE.fullmatch(scope) for scope in scopes):
            raise ValueError("grant scopes must be symbolic role/workstream scopes or *")
        return cls(
            principal=str(value["principal"]),
            capabilities=frozenset(map(str, value.get("capabilities", ()))),
            scopes=scopes,
        )


def resolve_role(installation: Mapping[str, Any], role: str) -> int:
    roles = installation.get("roles")
    if not isinstance(roles, Mapping) or role not in roles:
        raise ValueError(f"unmapped symbolic role: {role}")
    value = roles[role]
    if not isinstance(value, int):
        raise ValueError(f"ambiguous symbolic role mapping: {role}")
    return value


def event_is_authorized(
    event: Mapping[str, Any],
    grants: Iterable[PrincipalGrant],
    *,
    capability: str,
    scope: str,
) -> bool:
    """Decide state effect; unauthorized marker events remain audit-visible upstream."""
    if not _SCOPE.fullmatch(scope) or scope.startswith("#"):
        return False
    actor = event.get("actor") or event.get("github_actor")
    if not isinstance(actor, str) or not actor:
        return False
    matching = [grant for grant in grants if grant.principal == actor]
    if len(matching) != 1:
        return False
    grant = matching[0]
    return capability in grant.capabilities and ("*" in grant.scopes or scope in grant.scopes)


def package_manifest(
    installation: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    components: Sequence[Mapping[str, str]] = (),
    actions: Sequence[Mapping[str, str]] = (),
    package_version: str = "1",
) -> dict[str, Any]:
    """Build deterministic release identity and reject mutable Action references."""
    validate_persisted_input(installation)
    validate_persisted_input(config)
    normalized_actions = []
    for action in actions:
        uses = str(action.get("uses", ""))
        if "@" not in uses or not re.fullmatch(r"[^@]+@[0-9a-fA-F]{40}", uses):
            raise ValueError("third-party executable Action refs must use immutable 40-hex SHA")
        normalized_actions.append(dict(action))
    seed = {
        "package_version": package_version,
        "installation_id": deterministic_identity("installation", installation),
        "config_id": deterministic_identity("config", config),
        "components": sorted((dict(x) for x in components), key=canonical_json),
        "actions": sorted(normalized_actions, key=canonical_json),
    }
    return {**seed, "release_id": deterministic_identity("release", seed)}


def plan_single_repo_reconcile(
    installation: Mapping[str, Any],
    config: Mapping[str, Any],
    observed: Sequence[Mapping[str, str] | str],
) -> list[dict[str, str]]:
    """Return deterministic create/adopt/abort plan; never mutates GitHub."""
    validate_persisted_input(installation)
    validate_persisted_input(config)
    repo = installation.get("repository") or installation.get("repo")
    if isinstance(repo, Mapping):
        owner, name = repo.get("owner"), repo.get("name")
        repo = f"{owner}/{name}" if owner and name else None
    if not isinstance(repo, str) or not repo:
        raise ValueError("installation requires repository identity")
    required = config.get("required_paths", ())
    if not isinstance(required, list) or not all(isinstance(p, str) and p for p in required):
        raise ValueError("config.required_paths must be a list of non-empty strings")
    inventory: dict[str, str] = {}
    for item in observed:
        if isinstance(item, str):
            inventory[item] = "managed"
        else:
            inventory[str(item["path"])] = str(item.get("ownership", "foreign"))
    plan = []
    for path in sorted(set(required)):
        ownership = inventory.get(path)
        op = "create" if ownership is None else "adopt" if ownership == "managed" else "abort"
        plan.append({
            "op": op,
            "repository": repo,
            "path": path,
            "resource_id": deterministic_identity("managed-resource", {"repository": repo, "path": path}),
        })
    return plan
