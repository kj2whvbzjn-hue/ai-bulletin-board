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
    principal:str
    capabilities:frozenset[str]
    scopes:frozenset[str]
    @classmethod
    def from_mapping(cls,value:Mapping[str,Any])->"PrincipalGrant":
        scopes=frozenset(map(str,value.get("scopes",value.get("task_scope",()))))
        if not scopes or any(not _SCOPE.fullmatch(s) for s in scopes): raise ValueError("grant scopes must be symbolic role/workstream scopes or *")
        principal=str(value.get("principal",value.get("principal_id","")))
        capabilities=frozenset(map(str,value.get("capabilities",())))
        if not principal or not capabilities: raise ValueError("grant requires mapped principal and capability")
        return cls(principal,capabilities,scopes)

def validate_authorization_policy(policy:Mapping[str,Any],grants:Iterable[PrincipalGrant])->tuple[PrincipalGrant,...]:
    principals=policy.get("principals")
    if not isinstance(principals,Mapping): raise ValueError("authorization policy requires principals mapping")
    checked=[]
    for grant in grants:
        declared=principals.get(grant.principal)
        if not isinstance(declared,Mapping): raise ValueError(f"unmapped principal: {grant.principal}")
        capabilities=declared.get("capabilities")
        if not isinstance(capabilities,list) or not set(grant.capabilities).issubset(set(map(str,capabilities))):
            raise ValueError(f"grant capability exceeds principal policy: {grant.principal}")
        checked.append(grant)
    return tuple(checked)

def resolve_role(installation:Mapping[str,Any],role:str)->int:
    roles=installation.get("roles")
    if not isinstance(roles,Mapping) or role not in roles: raise ValueError(f"unmapped symbolic role: {role}")
    value=roles[role]
    if not isinstance(value,int): raise ValueError(f"ambiguous symbolic role mapping: {role}")
    return value

def event_is_authorized(event:Mapping[str,Any],grants:Iterable[PrincipalGrant],*,capability:str,scope:str,policy:Mapping[str,Any])->bool:
    if not _SCOPE.fullmatch(scope): return False
    actor=event.get("actor") or event.get("github_actor")
    if not isinstance(actor,str) or not actor: return False
    try: checked=validate_authorization_policy(policy,grants)
    except ValueError: return False
    matching=[g for g in checked if g.principal==actor]
    if len(matching)!=1:return False
    g=matching[0]
    return capability in g.capabilities and ("*" in g.scopes or scope in g.scopes)

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
