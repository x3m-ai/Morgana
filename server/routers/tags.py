"""
Tags router v2 - Full typed tag system for Morgana.

Tag Definitions:
  GET    /api/v2/tags                           list all (filtered by namespace/type/scope)
  POST   /api/v2/tags                           create tag definition
  PUT    /api/v2/tags/{id}                      update tag definition
  DELETE /api/v2/tags/{id}                      delete tag definition + all assignments

Tag Assignments (entity tagging):
  GET    /api/v2/tags/entity/{type}/{id}        get tags for entity
  POST   /api/v2/tags/entity/{type}/{id}        assign tag to entity
  DELETE /api/v2/tags/entity/{type}/{id}/{tid}  remove tag assignment

Workspaces:
  GET    /api/v2/tags/workspaces                list workspaces
  POST   /api/v2/tags/workspaces                create workspace
  PUT    /api/v2/tags/workspaces/{id}           update workspace
  DELETE /api/v2/tags/workspaces/{id}           delete workspace
  POST   /api/v2/tags/workspaces/{id}/activate  activate workspace (deactivates others)
  DELETE /api/v2/tags/workspaces/active         deactivate all workspaces

Queries:
  POST   /api/v2/tags/query                     query entities by tag selector
  POST   /api/v2/tags/resolve-agents            resolve agents matching a tag selector
  GET    /api/v2/tags/effective/{type}/{id}     get effective tags for entity

Tag Namespaces:
  GET    /api/v2/tags/namespaces                list distinct namespaces
"""
import json
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config import settings
from core.auth import require_api_key
from database import get_db
from models.tag import TagDefinition, TagAssignment, TagWorkspace, TAG_TYPES, ENTITY_TYPES
from models.agent import Agent
from core.tag_selector import resolve_agents, filter_entities, parse_selector

log = logging.getLogger("morgana.router.tags")
router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _td(t: TagDefinition, db: Session) -> dict:
    d = t.to_dict()
    d["usage_count"] = db.query(TagAssignment).filter(TagAssignment.tag_id == t.id).count()
    # Backward-compat aliases so old JS still works
    d["name"] = d.get("label", "")
    d["group_name"] = d.get("namespace", "general")
    return d


def _validate_scope(scope_json: str, entity_type: Optional[str] = None) -> list:
    """Parse scope JSON and optionally validate entity_type against it."""
    try:
        scope_list = json.loads(scope_json or '["all"]')
    except Exception:
        scope_list = ["all"]
    if entity_type and "all" not in scope_list and entity_type not in scope_list:
        raise HTTPException(
            status_code=422,
            detail=f"Tag scope {scope_list} does not include entity type '{entity_type}'"
        )
    return scope_list


# ─────────────────────────────────────────────────────────────────────────────
# Tag Definition CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_tags(
    namespace: Optional[str] = Query(None),
    tag_type: Optional[str] = Query(None),
    scope_filter: Optional[str] = Query(None, alias="scope"),
    runtime_only: bool = Query(False),
    filterable_only: bool = Query(False),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    q = db.query(TagDefinition)
    if namespace:
        q = q.filter(TagDefinition.namespace == namespace)
    if tag_type:
        q = q.filter(TagDefinition.tag_type == tag_type)
    if runtime_only:
        q = q.filter(TagDefinition.is_runtime_param == True)
    if filterable_only:
        q = q.filter(TagDefinition.is_filterable == True)
    tags = q.order_by(TagDefinition.namespace, TagDefinition.label).all()
    # Optional client-side scope filter
    if scope_filter:
        tags = [t for t in tags if "all" in (t.scope or "all") or scope_filter in (t.scope or "")]
    return [_td(t, db) for t in tags]


@router.post("", status_code=201)
def create_tag(payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    label = (payload.get("label") or "").strip()
    key = (payload.get("key") or label).strip().lower()
    if not label:
        raise HTTPException(status_code=422, detail="'label' is required")
    if not key:
        raise HTTPException(status_code=422, detail="'key' is required")

    tag_type = payload.get("tag_type", "flag")
    if tag_type not in TAG_TYPES:
        raise HTTPException(status_code=422, detail=f"tag_type must be one of: {sorted(TAG_TYPES)}")

    # scope: accept string "all" or JSON array
    scope_raw = payload.get("scope", '["all"]')
    if isinstance(scope_raw, list):
        scope_json = json.dumps(scope_raw)
    elif isinstance(scope_raw, str):
        try:
            parsed = json.loads(scope_raw)
            scope_json = json.dumps(parsed if isinstance(parsed, list) else [parsed])
        except Exception:
            scope_json = json.dumps([scope_raw])
    else:
        scope_json = '["all"]'

    # Validate allowed_values for enum type
    allowed_values = payload.get("allowed_values")
    if tag_type == "enum" and not allowed_values:
        raise HTTPException(status_code=422, detail="allowed_values required for enum type")
    if allowed_values and isinstance(allowed_values, list):
        allowed_values = json.dumps(allowed_values)

    tag = TagDefinition(
        label=label,
        key=key,
        value=(payload.get("value") or "").strip() or None,
        namespace=(payload.get("namespace") or "general").strip().lower(),
        tag_type=tag_type,
        description=payload.get("description"),
        color=payload.get("color", "#667eea"),
        icon=payload.get("icon"),
        scope=scope_json,
        allowed_values=allowed_values,
        default_value=payload.get("default_value"),
        is_system=bool(payload.get("is_system", False)),
        is_filterable=bool(payload.get("is_filterable", True)),
        is_assignable=bool(payload.get("is_assignable", True)),
        is_runtime_param=bool(payload.get("is_runtime_param", False)),
        is_inheritable=bool(payload.get("is_inheritable", False)),
        capabilities=json.dumps(payload.get("capabilities", {}))
            if isinstance(payload.get("capabilities"), dict)
            else (payload.get("capabilities") or "{}"),
    )
    db.add(tag)
    try:
        db.commit()
        db.refresh(tag)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A tag with this key+value+namespace already exists")
    log.info("[TAG] Created: %s/%s (%s)", tag.namespace, tag.label, tag.tag_type)
    return _td(tag, db)


@router.put("/{tag_id}")
def update_tag(tag_id: str, payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    tag = db.query(TagDefinition).filter(TagDefinition.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.is_system:
        raise HTTPException(status_code=403, detail="System tags cannot be modified")

    if "label" in payload and payload["label"]:
        tag.label = payload["label"].strip()
    if "key" in payload and payload["key"]:
        tag.key = payload["key"].strip().lower()
    if "value" in payload:
        tag.value = (payload["value"] or "").strip() or None
    if "namespace" in payload and payload["namespace"]:
        tag.namespace = payload["namespace"].strip().lower()
    if "tag_type" in payload:
        if payload["tag_type"] not in TAG_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid tag_type")
        tag.tag_type = payload["tag_type"]
    if "description" in payload:
        tag.description = payload["description"]
    if "color" in payload:
        tag.color = payload["color"]
    if "icon" in payload:
        tag.icon = payload["icon"]
    if "scope" in payload:
        sv = payload["scope"]
        tag.scope = json.dumps(sv) if isinstance(sv, list) else sv
    if "allowed_values" in payload:
        av = payload["allowed_values"]
        tag.allowed_values = json.dumps(av) if isinstance(av, list) else av
    if "default_value" in payload:
        tag.default_value = payload["default_value"]
    if "is_filterable" in payload:
        tag.is_filterable = bool(payload["is_filterable"])
    if "is_assignable" in payload:
        tag.is_assignable = bool(payload["is_assignable"])
    if "is_runtime_param" in payload:
        tag.is_runtime_param = bool(payload["is_runtime_param"])
    if "is_inheritable" in payload:
        tag.is_inheritable = bool(payload["is_inheritable"])
    if "capabilities" in payload:
        cap = payload["capabilities"]
        tag.capabilities = json.dumps(cap) if isinstance(cap, dict) else (cap or "{}")

    try:
        db.commit()
        db.refresh(tag)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate key+value+namespace")
    return _td(tag, db)


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    tag = db.query(TagDefinition).filter(TagDefinition.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.is_system:
        raise HTTPException(status_code=403, detail="System tags cannot be deleted")
    db.query(TagAssignment).filter(TagAssignment.tag_id == tag_id).delete()
    db.delete(tag)
    db.commit()
    log.info("[TAG] Deleted: %s (%s)", tag.label, tag_id)


# ─────────────────────────────────────────────────────────────────────────────
# Tag Namespaces
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/namespaces")
def list_namespaces(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    from sqlalchemy import distinct
    rows = db.query(distinct(TagDefinition.namespace)).order_by(TagDefinition.namespace).all()
    return [r[0] for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Tag Assignments (entity tagging)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/entity/{entity_type}/{entity_id}")
def get_entity_tags(
    entity_type: str, entity_id: str,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown entity type: {entity_type}")
    rows = db.query(TagAssignment).filter(
        TagAssignment.entity_type == entity_type,
        TagAssignment.entity_id == entity_id,
    ).all()
    result = []
    for row in rows:
        td = db.query(TagDefinition).filter(TagDefinition.id == row.tag_id).first()
        if td:
            d = _td(td, db)
            d["assignment_id"] = row.id
            d["value_override"] = row.value_override
            d["assigned_at"] = row.assigned_at.isoformat() if row.assigned_at else None
            result.append(d)
    return result


@router.post("/entity/{entity_type}/{entity_id}", status_code=201)
def assign_tag(
    entity_type: str, entity_id: str, payload: dict,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown entity type: {entity_type}")
    tag_id = payload.get("tag_id")
    if not tag_id:
        raise HTTPException(status_code=422, detail="'tag_id' is required")

    td = db.query(TagDefinition).filter(TagDefinition.id == tag_id).first()
    if not td:
        raise HTTPException(status_code=404, detail="Tag definition not found")
    if not td.is_assignable:
        raise HTTPException(status_code=422, detail="This tag is not assignable")

    # Scope validation
    _validate_scope(td.scope or '["all"]', entity_type)

    existing = db.query(TagAssignment).filter(
        TagAssignment.tag_id == tag_id,
        TagAssignment.entity_type == entity_type,
        TagAssignment.entity_id == entity_id,
    ).first()
    if existing:
        return {"id": existing.id, "duplicate": True}

    asn = TagAssignment(
        tag_id=tag_id,
        entity_type=entity_type,
        entity_id=entity_id,
        value_override=payload.get("value_override"),
    )
    db.add(asn)
    db.commit()
    log.info("[TAG] Assigned %s/%s to %s/%s", td.namespace, td.label, entity_type, entity_id)
    d = _td(td, db)
    d["assignment_id"] = asn.id
    d["value_override"] = asn.value_override
    return d


@router.delete("/entity/{entity_type}/{entity_id}/{tag_id}", status_code=204)
def remove_tag_assignment(
    entity_type: str, entity_id: str, tag_id: str,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    row = db.query(TagAssignment).filter(
        TagAssignment.tag_id == tag_id,
        TagAssignment.entity_type == entity_type,
        TagAssignment.entity_id == entity_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(row)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Effective tags (direct + inheritable from parent if needed)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/effective/{entity_type}/{entity_id}")
def get_effective_tags(
    entity_type: str, entity_id: str,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    """Return direct assignments. Inheritable propagation not implemented yet."""
    return get_entity_tags(entity_type, entity_id, db=db, _=_)


# ─────────────────────────────────────────────────────────────────────────────
# Tag Workspaces
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    ws = db.query(TagWorkspace).order_by(TagWorkspace.name).all()
    result = [w.to_dict() for w in ws]
    # Annotate with agent preview count for active workspace
    for item in result:
        if item.get("is_active") and item.get("selector_expr"):
            try:
                matched = resolve_agents(item["selector_expr"], db)
                item["matched_agents"] = len(matched)
            except Exception:
                item["matched_agents"] = None
    return result


@router.post("/workspaces", status_code=201)
def create_workspace(payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required")
    selector = (payload.get("selector_expr") or "").strip()
    if not selector:
        raise HTTPException(status_code=422, detail="'selector_expr' is required")

    # Validate selector parses
    try:
        parse_selector(selector)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid selector expression: {exc}")

    ws = TagWorkspace(
        name=name,
        description=payload.get("description"),
        selector_expr=selector,
        is_active=False,
    )
    db.add(ws)
    try:
        db.commit()
        db.refresh(ws)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Workspace name already exists")
    log.info("[WORKSPACE] Created: %s", name)
    return ws.to_dict()


@router.put("/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: str, payload: dict,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    ws = db.query(TagWorkspace).filter(TagWorkspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if "name" in payload and payload["name"]:
        ws.name = payload["name"].strip()
    if "description" in payload:
        ws.description = payload["description"]
    if "selector_expr" in payload and payload["selector_expr"]:
        sel = payload["selector_expr"].strip()
        try:
            parse_selector(sel)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid selector: {exc}")
        ws.selector_expr = sel
    try:
        db.commit()
        db.refresh(ws)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Name already taken")
    return ws.to_dict()


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: str,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    ws = db.query(TagWorkspace).filter(TagWorkspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    db.delete(ws)
    db.commit()


@router.post("/workspaces/{workspace_id}/activate")
def activate_workspace(
    workspace_id: str,
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    ws = db.query(TagWorkspace).filter(TagWorkspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # Deactivate all others
    db.query(TagWorkspace).update({"is_active": False})
    ws.is_active = True
    db.commit()
    db.refresh(ws)
    log.info("[WORKSPACE] Activated: %s", ws.name)
    return ws.to_dict()


@router.delete("/workspaces/active", status_code=204)
def deactivate_workspace(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    db.query(TagWorkspace).update({"is_active": False})
    db.commit()
    log.info("[WORKSPACE] All workspaces deactivated")


@router.get("/workspaces/active")
def get_active_workspace(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    ws = db.query(TagWorkspace).filter(TagWorkspace.is_active == True).first()
    if not ws:
        return None
    return ws.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Selector Queries
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/query")
def query_entities_by_selector(
    payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    """
    Filter entities by a tag selector expression.

    Body:
      {
        "entity_type": "agent" | "script" | "chain" | ...,
        "entity_ids": ["id1", "id2", ...],   // optional; if omitted fetches all IDs
        "selector_expr": "os=windows AND env=prod"
      }

    Returns list of matching entity_ids.
    """
    entity_type = payload.get("entity_type")
    if not entity_type or entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"entity_type must be one of {sorted(ENTITY_TYPES)}")
    selector = (payload.get("selector_expr") or "").strip()
    if not selector:
        raise HTTPException(status_code=422, detail="'selector_expr' is required")

    entity_ids = payload.get("entity_ids")
    if not entity_ids:
        # Fetch all IDs for this entity type from tag_assignments
        rows = db.query(TagAssignment.entity_id).filter(
            TagAssignment.entity_type == entity_type
        ).distinct().all()
        entity_ids = [r[0] for r in rows]

    matched = filter_entities(selector, entity_type, entity_ids, db)
    return {"entity_type": entity_type, "selector_expr": selector, "matched_ids": matched}


@router.post("/resolve-agents")
def resolve_agents_by_selector(
    payload: dict, db: Session = Depends(get_db), _: str = Depends(require_api_key),
):
    """
    Resolve all online agents matching a tag selector.

    Body: { "selector_expr": "os=windows AND env=prod" }
    Returns: list of agent dicts (paw, hostname, status, ip_address)
    """
    selector = (payload.get("selector_expr") or "").strip()
    if not selector:
        raise HTTPException(status_code=422, detail="'selector_expr' is required")

    try:
        agents = resolve_agents(selector, db)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Selector error: {exc}")

    return {
        "selector_expr": selector,
        "count": len(agents),
        "agents": [
            {
                "id": a.id, "paw": a.paw, "hostname": a.hostname,
                "status": a.status, "ip_address": a.ip_address, "platform": a.platform,
            }
            for a in agents
        ],
    }


# ── Resolve agents by shared tags with an entity ─────────────────────────────

@router.get("/resolve-agents-by-entity")
def resolve_agents_by_entity(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """
    Return all agents that share at least one tag with the given entity.
    Used by the __TAGS__ broadcast mode: execute on agents that have the same
    tags as this script / chain / campaign.
    """
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown entity type: {entity_type}")

    # Tags assigned to the source entity
    entity_tag_ids = [
        row.tag_id for row in db.query(TagAssignment).filter(
            TagAssignment.entity_type == entity_type,
            TagAssignment.entity_id == str(entity_id),
        ).all()
    ]
    if not entity_tag_ids:
        return {"agents": [], "count": 0, "entity_type": entity_type, "entity_id": entity_id, "tag_ids": []}

    # Agents that have at least one of those tags
    agent_assignments = db.query(TagAssignment).filter(
        TagAssignment.entity_type == "agent",
        TagAssignment.tag_id.in_(entity_tag_ids),
    ).all()

    matched_paws = list({a.entity_id for a in agent_assignments})
    agents = db.query(Agent).filter(Agent.paw.in_(matched_paws)).all() if matched_paws else []

    log.info("[TAG] resolve-agents-by-entity: %s/%s -> %d agent(s)", entity_type, entity_id, len(agents))
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "tag_ids": entity_tag_ids,
        "count": len(agents),
        "agents": [
            {
                "id": a.id, "paw": a.paw, "hostname": a.hostname,
                "status": a.status, "ip_address": a.ip_address, "platform": a.platform,
            }
            for a in agents
        ],
    }
