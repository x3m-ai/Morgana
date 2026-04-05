"""
Morgana - Visibility scope engine.

Resolves which entities a user is allowed to see based on:
  - workspaces assigned to the user (JSON array of TagWorkspace IDs, or ["__ALL__"])
  - tags directly assigned to the user

Rules:
  - Admin users always see everything.
  - User with ["__ALL__"] workspaces and no tag restrictions sees everything.
  - User with specific workspaces sees only entities matching at least one workspace.
  - User with tag restrictions: entities must share at least one tag with the user.
  - Combined workspace + tag: entity must satisfy BOTH constraints (intersection, not union).

Usage:
    from core.visibility import get_user_scope, apply_scope_to_id_list

    scope  = get_user_scope(current_user, db)
    if scope["all_workspaces"] and not scope["tag_ids"]:
        # unrestricted - no filtering needed
        pass
    else:
        visible_ids = apply_scope_to_id_list(entity_type, all_ids, scope, db)
"""

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from models.user import User

log = logging.getLogger("morgana.visibility")

_SELECTOR_CACHE: dict = {}  # simple in-process cache for workspace selectors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_user_scope(user: User, db: Session) -> dict:
    """
    Return a visibility scope dict for the given user.

    Schema:
    {
        "all_workspaces": bool,        # True = no workspace restriction
        "workspace_ids":  [str, ...],  # TagWorkspace IDs to filter by (empty if all_workspaces)
        "tag_ids":        [str, ...],  # User's own tag IDs (further restriction)
        "unrestricted":   bool,        # True = all_workspaces AND no tag filter -> see everything
    }
    """
    # Admin always sees everything
    if user.role == "admin":
        return {"all_workspaces": True, "workspace_ids": [], "tag_ids": [], "unrestricted": True}

    # Parse workspace list
    try:
        wss = json.loads(user.workspaces or '["__ALL__"]')
    except Exception:
        wss = ["__ALL__"]

    all_ws       = "__ALL__" in wss
    workspace_ids = [] if all_ws else wss

    # Tags assigned to this user
    from models.tag import TagAssignment
    user_tag_rows = db.query(TagAssignment).filter(
        TagAssignment.entity_type == "user",
        TagAssignment.entity_id   == user.id,
    ).all()
    tag_ids = [r.tag_id for r in user_tag_rows]

    unrestricted = all_ws and not tag_ids

    return {
        "all_workspaces": all_ws,
        "workspace_ids":  workspace_ids,
        "tag_ids":        tag_ids,
        "unrestricted":   unrestricted,
    }


def is_entity_visible(
    entity_id:   str,
    entity_type: str,
    scope:       dict,
    db:          Session,
) -> bool:
    """
    Returns True if the entity is visible under the given scope.
    Fast-path: if scope is unrestricted, always returns True.
    """
    if scope.get("unrestricted"):
        return True

    # Fetch entity's own tags
    from models.tag import TagAssignment
    rows            = db.query(TagAssignment).filter(
        TagAssignment.entity_type == entity_type,
        TagAssignment.entity_id   == entity_id,
    ).all()
    entity_tag_ids = {r.tag_id for r in rows}

    # ---- Workspace check ----
    if not scope["all_workspaces"]:
        if not _entity_in_any_workspace(entity_tag_ids, scope["workspace_ids"], db):
            return False

    # ---- Tag check ----
    if scope["tag_ids"]:
        if not entity_tag_ids.intersection(scope["tag_ids"]):
            return False

    return True


def filter_id_list(
    entity_type: str,
    entity_ids:  list,
    scope:       dict,
    db:          Session,
) -> list:
    """Filter a list of entity IDs to only those visible under scope."""
    if scope.get("unrestricted"):
        return entity_ids
    return [eid for eid in entity_ids if is_entity_visible(eid, entity_type, scope, db)]


def filter_dicts(
    entity_type: str,
    items:       list,
    scope:       dict,
    db:          Session,
    id_key:      str = "id",
) -> list:
    """Filter a list of dicts to only those visible under scope."""
    if scope.get("unrestricted"):
        return items
    return [item for item in items if is_entity_visible(item[id_key], entity_type, scope, db)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _entity_in_any_workspace(entity_tag_ids: set, workspace_ids: list, db: Session) -> bool:
    """Return True if entity's tags match at least one workspace selector."""
    from models.tag import TagWorkspace

    for ws_id in workspace_ids:
        ws = db.query(TagWorkspace).filter(TagWorkspace.id == ws_id).first()
        if not ws:
            continue
        if _matches_selector(entity_tag_ids, ws.selector_expr or ""):
            return True
    return False


def _matches_selector(entity_tag_ids: set, selector_expr: str) -> bool:
    """
    Evaluate a simple workspace selector expression against an entity's tag set.

    Selector format: tag a JSON array of tag_ids (legacy) or a DSL in future.
    Empty selector = matches all entities.
    """
    if not selector_expr or selector_expr.strip() in ("", "[]"):
        return True

    try:
        tag_id_list = json.loads(selector_expr)
        if isinstance(tag_id_list, list):
            # Must match at least one
            return bool(entity_tag_ids.intersection(tag_id_list))
    except Exception:
        pass

    # Fallback: treat raw string as a single tag_id
    return selector_expr in entity_tag_ids
