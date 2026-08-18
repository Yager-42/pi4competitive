"""Plan-output deterministic guardrail — aggregate-row expansion (v0.2.11).

Root cause (live DRB II smoke): the plan LLM ignores the ENTITY GRANULARITY
prompt guidance and emits aggregate/umbrella rows — the whole topic and the
category become entities, so a brief that enumerates concrete items (e.g. 12
countries for an incentive-policy table) cannot be searched per-item. Every
value gets crammed into one aggregate cell, search fills nothing, and the write
stage has no per-item material (it repeats the one surviving table across every
section).

This module deterministically repairs the plan's coverage_schema, WITHOUT
relying on the LLM: it extracts the brief's enumerated item list, creates one
entity per item, and scopes the policy-class attributes to those item entities
via the optional ``entity_attributes`` field (CoverageMap.from_schema). The
original aggregate entities keep only the non-policy attributes, so they stop
collecting crammed policy cells.

No enumerated items or no policy attributes → plan returned unchanged
(backward compatible; well-formed plans pass through untouched).

Isomorphic note: this is a competitive_app application-layer repair, not a
change to upstream ``packages/agent`` — the coverage-schema shape stays the
plan stage's contract (F-R26); only the optional field is new.
"""
from __future__ import annotations

import re
from typing import Any

# Attribute names/ids containing any of these are "policy-class" (belong to
# per-country/per-entity policy rows rather than an aggregate subject row).
_POLICY_KEYWORDS = ("country", "policy", "regulation", "incentive", "subsidy")

# Brief phrases that introduce an explicit item enumeration.
_TRIGGERS = re.compile(
    r"(?i)(?:at least|such as|including|namely|the following|each of)\b"
)

# A capitalized phrase that looks like a concrete named item (allows spaces,
# hyphens, parentheses, dots, apostrophes). Requires at least one lowercase
# letter so pure acronyms (US, EU, LED) don't register as items.
_PHRASE = re.compile(r"[A-Z][A-Za-z'\-()\.]*(?:\s+[A-Za-z][A-Za-z'\-()\.]*)*")

_MAX_ITEMS = 40


def _extract_enumerated_items(goal: str) -> list[str]:
    """Extract the brief's enumerated concrete items (countries/models/...).

    Matches the comma/semicolon/"and"-separated capitalized list that follows a
    trigger phrase ("cover at least Canada, the United States, Spain, ...").
    Returns deduped, order-preserving item names. Tolerant: no trigger / no
    list → empty list.
    """
    items: list[str] = []
    for m in _TRIGGERS.finditer(goal or ""):
        rest = goal[m.end():]
        clause_end = re.search(r"[.!?\n]", rest)
        clause = rest if clause_end is None else rest[: clause_end.start()]
        for p in _PHRASE.finditer(clause):
            phrase = p.group().strip()
            if 2 <= len(phrase) <= 45 and any(ch.islower() for ch in phrase):
                items.append(phrase)
            if len(items) >= _MAX_ITEMS:
                break
    return list(dict.fromkeys(items))


def _is_policy_attr(attr: Any) -> bool:
    """True when an attribute's name/id marks it policy-class."""
    if not isinstance(attr, dict):
        return False
    blob = f"{attr.get('name') or ''} {attr.get('id') or ''}".lower()
    return any(k in blob for k in _POLICY_KEYWORDS)


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return out[:48] or "item"


def _has_entity_named(entities: list[Any], name: str) -> bool:
    low = name.lower()
    return any(
        isinstance(e, dict) and (e.get("name") or "").lower() == low
        for e in entities
    )


def normalize_plan_output(plan: Any, goal: str) -> Any:
    """Repair a plan's aggregate-row coverage_schema (deterministic, v0.2.11).

    When the brief enumerates >= 2 concrete items and the schema carries
    policy-class attributes with no matching per-item entity yet:

    - create one entity per item (``kind: competitor``, ``id: item_<slug>``);
    - scope the policy attributes to those item entities and the non-policy
      attributes to the original entities, via ``entity_attributes`` (the
      plan's own scoping wins for entities it already scoped);
    - append one targeted search query per new entity.

    Any other plan passes through unchanged.
    """
    if not isinstance(plan, dict):
        return plan
    schema = plan.get("coverage_schema")
    if not isinstance(schema, dict):
        return plan
    attributes = schema.get("attributes")
    entities = schema.get("entities")
    if not isinstance(attributes, list) or not isinstance(entities, list):
        return plan

    policy_attrs = [a for a in attributes if _is_policy_attr(a)]
    if not policy_attrs:
        return plan  # no policy dimension → nothing to expand

    items = [
        it
        for it in _extract_enumerated_items(goal or "")
        if not _has_entity_named(entities, it)
    ]
    if len(items) < 2:
        return plan

    attr_ids = {str(a.get("id")) for a in attributes if isinstance(a, dict) and a.get("id")}
    policy_ids = sorted({str(a.get("id")) for a in policy_attrs if a.get("id")})
    other_ids = sorted(attr_ids - set(policy_ids))

    new_entities = [
        {"id": f"item_{_slug(it)}", "name": it, "kind": "competitor"} for it in items
    ]

    # Scoping: item entities → policy attrs; original entities → non-policy.
    scope_for: dict[str, list[str]] = {}
    for e in entities:
        if isinstance(e, dict) and e.get("id"):
            scope_for[str(e["id"])] = list(other_ids)
    for ne in new_entities:
        scope_for[ne["id"]] = list(policy_ids)

    schema_out = dict(schema)
    schema_out["entities"] = list(entities) + new_entities
    existing_scope = schema_out.get("entity_attributes")
    merged_scope = dict(existing_scope) if isinstance(existing_scope, dict) else {}
    for eid, ids in scope_for.items():
        if eid not in merged_scope:  # plan's own scoping wins for scoped entities
            merged_scope[eid] = ids
    schema_out["entity_attributes"] = merged_scope

    focus = " ".join(sorted({str(a.get("name")) for a in policy_attrs if a.get("name")}))
    focus = (focus or "policy")[:60]
    new_queries = [
        {
            "entity_id": ne["id"],
            "queries": [f"{it} {focus}"],
            "source_hints": [],
        }
        for it, ne in zip(items, new_entities)
    ]
    existing_queries = schema_out.get("queries")
    if isinstance(existing_queries, list):
        schema_out["queries"] = existing_queries + new_queries
    else:
        schema_out["queries"] = new_queries

    return {**plan, "coverage_schema": schema_out}


__all__ = ["normalize_plan_output"]
