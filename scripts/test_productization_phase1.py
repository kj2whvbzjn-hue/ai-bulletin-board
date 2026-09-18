#!/usr/bin/env python3
"""Offline deterministic acceptance checks for Productization v1 Phase 1."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from productization_v1 import (
    PrincipalGrant,
    event_is_authorized,
    package_manifest,
    plan_single_repo_reconcile,
    resolve_role,
    validate_persisted_input,
)


def must_fail(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except (ValueError, KeyError):
        return
    raise AssertionError("expected fail-closed validation")


def main() -> None:
    grant = PrincipalGrant.from_mapping({
        "principal": "octo-app",
        "capabilities": ["claim"],
        "scopes": ["role:manager"],
    })
    grants = [grant]
    assert event_is_authorized({"actor": "octo-app", "agent_id": "audit-only"}, grants, capability="claim", scope="role:manager")
    assert not event_is_authorized({"actor": "intruder", "agent_id": "octo-app"}, grants, capability="claim", scope="role:manager")
    assert not event_is_authorized({"actor": "octo-app"}, grants, capability="review", scope="role:manager")
    assert not event_is_authorized({"actor": "octo-app"}, grants, capability="claim", scope="role:review_manager")
    assert not event_is_authorized({"actor": "octo-app"}, grants, capability="claim", scope="#16")
    must_fail(PrincipalGrant.from_mapping, {"principal": "octo-app", "capabilities": ["claim"], "scopes": ["#16"]})

    installation = {"repository": "example/project", "roles": {"manager": 101, "review_manager": 102}}
    other_installation = {"repository": "other/project", "roles": {"manager": 501, "review_manager": 502}}
    assert resolve_role(installation, "manager") == 101
    assert resolve_role(other_installation, "manager") == 501
    must_fail(resolve_role, installation, "missing")

    config = {"required_paths": [".github/workflows/core.yml", "protocol/core.md"], "deployment_secret_ref": "DEPLOY_TOKEN"}
    validate_persisted_input(config)
    must_fail(validate_persisted_input, {"deployment_token": "plaintext"})
    must_fail(validate_persisted_input, {"nested": {"password": "plaintext"}})

    components = [{"name": "core", "identity": "git:" + "a" * 40, "digest": "sha256:" + "b" * 64}]
    actions = [{"uses": "actions/checkout@" + "c" * 40}]
    first = package_manifest(installation, config, components=components, actions=actions)
    second = package_manifest(dict(installation), dict(config), components=list(components), actions=list(actions))
    assert first == second
    assert first["release_id"].startswith("release:sha256:")
    must_fail(package_manifest, installation, config, components=[{"name": "core", "identity": "git:abc", "digest": "sha256:" + "b" * 64}])
    must_fail(package_manifest, installation, config, actions=[{"uses": "actions/checkout@v4"}])
    must_fail(package_manifest, installation, config, components=[{"name": "core", "identity": "git:" + "a" * 40, "digest": "z" * 64}])
    must_fail(validate_persisted_input, {"private_key": "plaintext"})
    must_fail(validate_persisted_input, {"api_secret": "plaintext"})
    must_fail(validate_persisted_input, {"deployment_secret_ref": "literal-secret"})
    must_fail(validate_persisted_input, {"required_secret_refs": ["OK_TOKEN", "bad-ref"]})

    plan = plan_single_repo_reconcile(installation, config, [])
    assert [x["op"] for x in plan] == ["create", "create"]
    assert [x["path"] for x in plan] == sorted(config["required_paths"])
    observed = [x["path"] for x in plan]
    assert plan_single_repo_reconcile(installation, config, observed) == []

    adopt = plan_single_repo_reconcile(installation, {"required_paths": ["legacy.yml"]}, [{"path": "legacy.yml", "ownership": "foreign", "collision_action": "adopt"}])
    abort = plan_single_repo_reconcile(installation, {"required_paths": ["legacy.yml"]}, [{"path": "legacy.yml", "ownership": "foreign", "collision_action": "abort"}])
    assert adopt[0]["op"] == "adopt"
    assert abort[0]["op"] == "abort"
    assert adopt[0]["resource_id"] == abort[0]["resource_id"]
    must_fail(plan_single_repo_reconcile, installation, {"required_paths": ["legacy.yml"]}, [{"path": "legacy.yml", "ownership": "foreign"}])

    # Inputs use symbolic roles/repository identity, never fixed control Issue identity or historical title prefixes.
    assert "#" not in repr(installation)
    assert "#" not in repr(config)
    print("productization phase1 core: ok")


if __name__ == "__main__":
    main()
