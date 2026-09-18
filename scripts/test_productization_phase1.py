#!/usr/bin/env python3
"""Offline deterministic acceptance checks for Productization v1 Phase 1."""
from productization_v1 import (
    PrincipalGrant,
    event_is_authorized,
    package_manifest,
    plan_single_repo_reconcile,
)


def main() -> None:
    grants = [PrincipalGrant("octo-app", frozenset({"claim"}), frozenset({"role:manager"}))]
    assert event_is_authorized({"actor": "octo-app", "agent_id": "audit-only"}, grants, capability="claim", scope="role:manager")
    assert not event_is_authorized({"actor": "intruder", "agent_id": "octo-app"}, grants, capability="claim", scope="role:manager")
    assert not event_is_authorized({"actor": "octo-app"}, grants, capability="review", scope="role:manager")
    assert not event_is_authorized({"actor": "octo-app"}, grants, capability="claim", scope="role:review_manager")

    installation = {"repository": "example/project", "roles": {"manager": 101, "review_manager": 102}}
    config = {"required_paths": [".github/workflows/core.yml", "protocol/core.md"]}
    first = package_manifest(installation, config)
    second = package_manifest(dict(installation), dict(config))
    assert first == second
    assert first["release_id"].startswith("release:sha256:")

    plan = plan_single_repo_reconcile(installation, config, [])
    assert [x["path"] for x in plan] == sorted(config["required_paths"])
    observed = [x["path"] for x in plan]
    assert plan_single_repo_reconcile(installation, config, observed) == []

    # No fixed control Issue identity is needed by package inputs.
    assert "#" not in repr(installation)
    assert "#" not in repr(config)
    print("productization phase1 core: ok")


if __name__ == "__main__":
    main()
