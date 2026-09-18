#!/usr/bin/env python3
import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from productization_v1 import PrincipalGrant,event_is_authorized,package_manifest,plan_single_repo_reconcile,resolve_role,validate_authorization_policy,validate_persisted_input
def must_fail(fn,*a,**k):
    try: fn(*a,**k)
    except (ValueError,KeyError): return
    raise AssertionError("expected fail-closed validation")
def main():
    grant=PrincipalGrant.from_mapping({"principal":"octo-app","capabilities":["claim"],"scopes":["role:manager"]})
    policy={"principals":{"octo-app":{"capabilities":["claim","review"]}}}
    validate_authorization_policy(policy,[grant])
    assert event_is_authorized({"actor":"octo-app"},[grant],capability="claim",scope="role:manager",policy=policy)
    assert not event_is_authorized({"actor":"intruder"},[grant],capability="claim",scope="role:manager",policy=policy)
    assert not event_is_authorized({"actor":"octo-app"},[grant],capability="claim",scope="role:manager",policy={"principals":{}})
    escalated=PrincipalGrant.from_mapping({"principal":"octo-app","capabilities":["integrate"],"scopes":["*"]})
    must_fail(validate_authorization_policy,policy,[escalated])
    installation={"repository":"example/project","roles":{"manager":101,"review_manager":102}}
    assert resolve_role(installation,"manager")==101
    config={"required_paths":[".github/workflows/core.yml","protocol/core.md"],"deployment_secret_ref":"DEPLOY_TOKEN"}
    validate_persisted_input(config); must_fail(validate_persisted_input,{"deployment_token":"plaintext"})
    components={"core":{"repository":"example/core","commit_sha":"a"*40,"digest":"sha256:"+"b"*64},"workflows":{"repository":"example/workflows","commit_sha":"c"*40,"digest":"sha256:"+"d"*64}}
    actions=[{"uses":"actions/checkout@"+"e"*40}]
    first=package_manifest(installation,config,supported_profile="public-pages",components=components,actions=actions,sbom_digest="sha256:"+"f"*64)
    second=package_manifest(dict(installation),dict(config),supported_profile="public-pages",components=dict(components),actions=list(actions),sbom_digest="sha256:"+"f"*64)
    assert first==second and first["release_id"].startswith("release:sha256:")
    assert set(first)=={"release_id","supported_profile","components","actions","sbom_digest"}
    must_fail(package_manifest,installation,config,supported_profile="public-pages",components={"core":components["core"]},actions=actions,sbom_digest="sha256:"+"f"*64)
    must_fail(package_manifest,installation,config,supported_profile="public-pages",components=components,actions=[{"uses":"actions/checkout@v4"}],sbom_digest="sha256:"+"f"*64)
    plan=plan_single_repo_reconcile(installation,config,[])
    assert [x["op"] for x in plan]==["create","create"]
    assert plan_single_repo_reconcile(installation,config,[x["path"] for x in plan])==[]
    adopt=plan_single_repo_reconcile(installation,{"required_paths":["legacy.yml"]},[{"path":"legacy.yml","ownership":"foreign","collision_action":"adopt"}])
    assert adopt[0]["op"]=="adopt"
    must_fail(plan_single_repo_reconcile,installation,{"required_paths":["legacy.yml"]},[{"path":"legacy.yml","ownership":"foreign","collision_action":"abort"}])
    must_fail(plan_single_repo_reconcile,installation,{"required_paths":["legacy.yml","later.yml"]},[{"path":"legacy.yml","ownership":"foreign","collision_action":"abort"}])
    print("productization phase1 core: ok")
if __name__=="__main__": main()
