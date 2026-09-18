"""Reusable, tokenless Productization v1 Phase-1 core helpers."""
from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

_SCOPE=re.compile(r"^(?:\*|role:[a-z][a-z0-9_]*|workstream:[a-z0-9][a-z0-9._/-]*)$")
_SECRET_KEYS=("secret","token","password","private_key")
_SECRET_REF=re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_DIGEST=re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA=re.compile(r"^[0-9a-f]{40}$")
_PROFILES={"public-pages","private-no-public-console"}

def canonical_json(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def deterministic_identity(kind:str,value:Any)->str:
    return f"{kind}:sha256:{hashlib.sha256(canonical_json(value).encode()).hexdigest()}"

def validate_persisted_input(value:Any,path:str="$")->None:
    if isinstance(value,Mapping):
        for key,item in value.items():
            name=str(key).lower(); secret=any(m in name for m in _SECRET_KEYS)
            if secret and not name.endswith(("_ref","_refs","_name")): raise ValueError(f"secret value is not persistable at {path}.{key}")
            if secret and name.endswith(("_ref","_name")) and (not isinstance(item,str) or not _SECRET_REF.fullmatch(item)): raise ValueError(f"secret reference must be symbolic at {path}.{key}")
            if secret and name.endswith("_refs") and (not isinstance(item,list) or any(not isinstance(x,str) or not _SECRET_REF.fullmatch(x) for x in item)): raise ValueError(f"secret references must be symbolic at {path}.{key}")
            validate_persisted_input(item,f"{path}.{key}")
    elif isinstance(value,list):
        for i,item in enumerate(value): validate_persisted_input(item,f"{path}[{i}]")

@dataclass(frozen=True)
class PrincipalGrant:
    principal: str
    capabilities: frozenset[str]
    scopes: frozenset[str]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PrincipalGrant":
        principal = str(value.get("principal_id", value.get("principal", "")))
        if "capability" in value:
            capabilities = frozenset({str(value["capability"])})
        else:
            capabilities = frozenset(map(str, value.get("capabilities", ())))
        raw_scope = value.get("task_scope", value.get("scopes", ()))
        scopes = frozenset({raw_scope}) if isinstance(raw_scope, str) else frozenset(map(str, raw_scope))
        if not principal or not capabilities or not scopes or any(not _SCOPE.fullmatch(scope) for scope in scopes):
            raise ValueError("grant requires principal_id, capability, and symbolic task_scope")
        return cls(principal, capabilities, scopes)

def grants_from_authorization_policy(policy: Mapping[str, Any]) -> tuple[PrincipalGrant, ...]:
    principals = policy.get("principals")
    records = policy.get("state_effect_grants")
    if not isinstance(principals, list) or not isinstance(records, list):
        raise ValueError("authorization policy requires principals and state_effect_grants arrays")
    declared: dict[str, frozenset[str]] = {}
    for principal in principals:
        if not isinstance(principal, Mapping):
            raise ValueError("principal record must be an object")
        principal_id = str(principal.get("principal_id", ""))
        capabilities = principal.get("capabilities")
        if not principal_id or principal_id in declared or not isinstance(capabilities, list):
            raise ValueError("invalid or duplicate principal")
        declared[principal_id] = frozenset(map(str, capabilities))
    checked = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("grant record must be an object")
        grant = PrincipalGrant.from_mapping(record)
        if grant.principal not in declared:
            raise ValueError(f"unmapped principal: {grant.principal}")
        if not grant.capabilities.issubset(declared[grant.principal]):
            raise ValueError(f"grant capability exceeds principal policy: {grant.principal}")
        checked.append(grant)
    return tuple(checked)

def validate_authorization_policy(policy: Mapping[str, Any], grants: Iterable[PrincipalGrant] | None = None) -> tuple[PrincipalGrant, ...]:
    policy_grants = grants_from_authorization_policy(policy)
    if grants is None:
        return policy_grants
    supplied = tuple(grants)
    if supplied != policy_grants:
        raise ValueError("supplied grants do not match authorization policy")
    return supplied

def resolve_role(installation:Mapping[str,Any],role:str)->int:
    roles=installation.get("roles")
    if not isinstance(roles,Mapping) or role not in roles: raise ValueError(f"unmapped symbolic role: {role}")
    value=roles[role]
    if not isinstance(value,int): raise ValueError(f"ambiguous symbolic role mapping: {role}")
    return value

def event_is_authorized(event:Mapping[str,Any],grants:Iterable[PrincipalGrant]|None=None,*,capability:str,scope:str,policy:Mapping[str,Any])->bool:
    if not _SCOPE.fullmatch(scope): return False
    actor=event.get("actor") or event.get("github_actor")
    if not isinstance(actor,str) or not actor: return False
    try: checked=validate_authorization_policy(policy,grants)
    except ValueError: return False
    matching=[g for g in checked if g.principal==actor and capability in g.capabilities]
    return any("*" in g.scopes or scope in g.scopes for g in matching)

def package_manifest(installation:Mapping[str,Any],config:Mapping[str,Any],*,supported_profile:str,components:Mapping[str,Mapping[str,str]],actions:Sequence[Mapping[str,str]],sbom_digest:str)->dict[str,Any]:
    validate_persisted_input(installation); validate_persisted_input(config)
    if supported_profile not in _PROFILES: raise ValueError("unsupported profile")
    if not isinstance(components,Mapping) or not {"core","workflows"}.issubset(components): raise ValueError("release manifest requires core and workflows components")
    normalized={}
    for name,component in components.items():
        item=dict(component)
        if not re.fullmatch(r"[^/]+/[^/]+",str(item.get("repository",""))) or not _SHA.fullmatch(str(item.get("commit_sha",""))) or not _DIGEST.fullmatch(str(item.get("digest",""))): raise ValueError("components require repository, immutable commit_sha, and sha256 digest")
        normalized[str(name)]=item
    normalized_actions=[]
    for action in actions:
        uses=str(action.get("uses",""))
        if not re.fullmatch(r"[^@]+@[0-9a-f]{40}",uses): raise ValueError("third-party executable Action refs must use immutable 40-hex SHA")
        normalized_actions.append({"uses":uses})
    if not _DIGEST.fullmatch(sbom_digest): raise ValueError("release manifest requires sbom sha256 digest")
    seed={"supported_profile":supported_profile,"components":dict(sorted(normalized.items())),"actions":sorted(normalized_actions,key=canonical_json),"sbom_digest":sbom_digest}
    return {"release_id":deterministic_identity("release",seed),**seed}

def plan_single_repo_reconcile(installation:Mapping[str,Any],config:Mapping[str,Any],observed:Sequence[Mapping[str,str]|str])->list[dict[str,str]]:
    validate_persisted_input(installation); validate_persisted_input(config)
    repo=installation.get("repository") or installation.get("repo")
    if isinstance(repo,Mapping):
        owner,name=repo.get("owner"),repo.get("name"); repo=f"{owner}/{name}" if owner and name else None
    if not isinstance(repo,str) or not repo: raise ValueError("installation requires repository identity")
    required=config.get("required_paths",())
    if not isinstance(required,list) or not all(isinstance(p,str) and p for p in required): raise ValueError("config.required_paths must be a list of non-empty strings")
    inventory={}
    for item in observed:
        if isinstance(item,str): path,ownership,decision=item,"managed",None
        else: path,ownership,decision=str(item["path"]),str(item.get("ownership","foreign")),item.get("collision_action")
        if path in inventory: raise ValueError(f"ambiguous observed resource: {path}")
        if ownership!="managed" and decision not in {"adopt","abort"}: raise ValueError(f"collision requires explicit adopt/abort decision: {path}")
        if ownership!="managed" and decision=="abort": raise ValueError(f"reconcile aborted on foreign resource: {path}")
        inventory[path]=(ownership,decision)
    plan=[]
    for path in sorted(set(required)):
        state=inventory.get(path)
        if state and state[0]=="managed": continue
        op="create" if state is None else "adopt"
        plan.append({"op":op,"repository":repo,"path":path,"resource_id":deterministic_identity("managed-resource",{"repository":repo,"path":path})})
    return plan
