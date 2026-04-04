"""
core/tag_selector.py - Tag DSL parser, evaluator, and agent resolver.

Supports expressions like:
  os=windows AND env=prod
  critical OR stealth
  project=apollo AND NOT isolated
  (env=prod OR env=staging) AND NOT excluded

Grammar (simplified):
  expr   = or_expr
  or_expr  = and_expr  ( 'OR'  and_expr )*
  and_expr = not_expr  ( 'AND' not_expr )*
  not_expr = 'NOT' not_expr | atom
  atom     = '(' expr ')'  |  condition
  condition = key '=' value  |  label
"""

from __future__ import annotations
import re
import logging
from typing import List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger("morgana.tag_selector")


# ── Tokenizer ───────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r'\s*(?:'
    r'(AND|OR|NOT)\b'       # group 1: logic operator
    r'|(\(|\))'             # group 2: parenthesis
    r'|([A-Za-z0-9_\-\.]+=[A-Za-z0-9_\-\.]+)'  # group 3: key=value
    r'|([A-Za-z0-9_\-\.]+)'  # group 4: bare label/key
    r')',
    re.IGNORECASE,
)


def _tokenize(expr: str) -> list:
    tokens = []
    pos = 0
    s = expr.strip()
    for m in _TOKEN_RE.finditer(s):
        if m.group(1):
            tokens.append(("OP", m.group(1).upper()))
        elif m.group(2):
            tokens.append(("PAREN", m.group(2)))
        elif m.group(3):
            k, v = m.group(3).split("=", 1)
            tokens.append(("KV", k.lower(), v.lower()))
        elif m.group(4):
            tokens.append(("LABEL", m.group(4).lower()))
    return tokens


# ── AST nodes ───────────────────────────────────────────────────────────────

class _And:
    def __init__(self, left, right): self.left, self.right = left, right

class _Or:
    def __init__(self, left, right): self.left, self.right = left, right

class _Not:
    def __init__(self, child): self.child = child

class _KV:
    def __init__(self, key: str, value: str): self.key, self.value = key, value

class _Label:
    def __init__(self, label: str): self.label = label


# ── Parser ──────────────────────────────────────────────────────────────────

class _Parser:
    def __init__(self, tokens: list):
        self._t = tokens
        self._pos = 0

    def _peek(self):
        if self._pos < len(self._t):
            return self._t[self._pos]
        return None

    def _consume(self):
        tok = self._t[self._pos]
        self._pos += 1
        return tok

    def parse(self):
        node = self._or_expr()
        if self._peek() is not None:
            remaining = self._t[self._pos:]
            log.warning("[SELECTOR] Unparsed tokens: %s", remaining)
        return node

    def _or_expr(self):
        left = self._and_expr()
        while True:
            p = self._peek()
            if p and p[0] == "OP" and p[1] == "OR":
                self._consume()
                right = self._and_expr()
                left = _Or(left, right)
            else:
                break
        return left

    def _and_expr(self):
        left = self._not_expr()
        while True:
            p = self._peek()
            if p and p[0] == "OP" and p[1] == "AND":
                self._consume()
                right = self._not_expr()
                left = _And(left, right)
            else:
                break
        return left

    def _not_expr(self):
        p = self._peek()
        if p and p[0] == "OP" and p[1] == "NOT":
            self._consume()
            return _Not(self._not_expr())
        return self._atom()

    def _atom(self):
        p = self._peek()
        if p is None:
            return _Label("_never_")   # empty
        if p[0] == "PAREN" and p[1] == "(":
            self._consume()
            node = self._or_expr()
            closing = self._peek()
            if closing and closing[0] == "PAREN" and closing[1] == ")":
                self._consume()
            return node
        if p[0] == "KV":
            self._consume()
            return _KV(p[1], p[2])
        if p[0] == "LABEL":
            self._consume()
            return _Label(p[1])
        return _Label("_never_")


# ── Evaluator ───────────────────────────────────────────────────────────────

def _build_entity_tag_set(entity_tags: list) -> set:
    """
    Build a set of normalised tag descriptors from a list of tag dicts.

    Each dict should have at least "key" and optionally "value" from TagDefinition.
    Returns a set of strings like {"env=prod", "critical", "os=windows"}.
    """
    result = set()
    for td in entity_tags:
        k = (td.get("key") or "").lower()
        v = (td.get("value") or "").lower() if td.get("value") else None
        if v:
            result.add(f"{k}={v}")
        if k:
            result.add(k)
        # Also add the label lowercased
        lbl = (td.get("label") or "").lower()
        if lbl:
            result.add(lbl)
    return result


def _eval(node, tag_set: set) -> bool:
    if isinstance(node, _And):
        return _eval(node.left, tag_set) and _eval(node.right, tag_set)
    if isinstance(node, _Or):
        return _eval(node.left, tag_set) or _eval(node.right, tag_set)
    if isinstance(node, _Not):
        return not _eval(node.child, tag_set)
    if isinstance(node, _KV):
        return f"{node.key}={node.value}" in tag_set
    if isinstance(node, _Label):
        return node.label in tag_set
    return False


# ── Public API ───────────────────────────────────────────────────────────────

def parse_selector(expr: str):
    """Parse a selector expression string into an AST node."""
    if not expr or not expr.strip():
        return None
    tokens = _tokenize(expr.strip())
    return _Parser(tokens).parse()


def matches(expr: str, entity_tags: list) -> bool:
    """
    Return True if entity_tags satisfy the selector expression.

    entity_tags: list of TagDefinition dicts (with 'key', 'value', 'label' fields)
    """
    if not expr or not expr.strip():
        return True    # empty selector matches everything
    ast = parse_selector(expr)
    if ast is None:
        return True
    tag_set = _build_entity_tag_set(entity_tags)
    return _eval(ast, tag_set)


def resolve_agents(selector_expr: str, db: "Session") -> list:
    """
    Return all Agent records whose assigned tags match selector_expr.

    Returns list of Agent ORM objects.
    """
    from models.agent import Agent
    from models.tag import TagAssignment, TagDefinition

    agents = db.query(Agent).filter(Agent.status != "offline").all()
    if not selector_expr or not selector_expr.strip():
        return agents

    ast = parse_selector(selector_expr)
    if ast is None:
        return agents

    result = []
    for agent in agents:
        assignments = db.query(TagAssignment).filter(
            TagAssignment.entity_type == "agent",
            TagAssignment.entity_id == agent.id,
        ).all()
        tag_defs = []
        for asn in assignments:
            td = db.query(TagDefinition).filter(TagDefinition.id == asn.tag_id).first()
            if td:
                tag_defs.append(td.to_dict())
        tag_set = _build_entity_tag_set(tag_defs)
        if _eval(ast, tag_set):
            result.append(agent)
    return result


def filter_entities(selector_expr: str, entity_type: str, entity_ids: list, db: "Session") -> list:
    """
    Filter entity_ids to those whose assigned tags match selector_expr.
    Returns filtered list of entity_ids (strings).
    """
    from models.tag import TagAssignment, TagDefinition

    if not selector_expr or not selector_expr.strip():
        return entity_ids

    ast = parse_selector(selector_expr)
    if ast is None:
        return entity_ids

    result = []
    for eid in entity_ids:
        assignments = db.query(TagAssignment).filter(
            TagAssignment.entity_type == entity_type,
            TagAssignment.entity_id == eid,
        ).all()
        tag_defs = []
        for asn in assignments:
            td = db.query(TagDefinition).filter(TagDefinition.id == asn.tag_id).first()
            if td:
                tag_defs.append(td.to_dict())
        tag_set = _build_entity_tag_set(tag_defs)
        if _eval(ast, tag_set):
            result.append(eid)
    return result


def resolve_tag_placeholders(content: str, params: dict) -> tuple[str, list]:
    """
    Substitute [PARAM_KEY] placeholders in content with values from params dict.

    params: {KEY: value_string}
    Returns (resolved_content, list_of_missing_keys).
    """
    missing = []
    result = content
    placeholder_re = re.compile(r'\[([A-Z0-9_]+)\]')
    for m in placeholder_re.finditer(content):
        key = m.group(1)
        if key in params:
            result = result.replace(m.group(0), str(params[key]))
        else:
            missing.append(key)
    return result, missing
