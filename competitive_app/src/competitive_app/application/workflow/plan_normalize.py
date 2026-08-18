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

# Words that mark a trigger as a COLUMN/ATTRIBUTE spec rather than a row-entity
# enumeration — e.g. "with columns including: 'Vehicle Model/Study Code', ...".
# The items after those are table headers (attributes), not rows to expand.
# ("rows" is deliberately absent: "rows including: X, Y" IS a row enumeration.)
_SPEC_WORDS = re.compile(
    r"(columns?|fields?|attributes?|properties?|parameters?|metrics?|headers?|keys?|schemas?|formats?|sections?|articles?|papers?|urls?)",
    re.IGNORECASE,
)

# Clause terminator: a trigger's list ends at a sentence boundary OR the start
# of a structured block ("{...}" / "[...]" — e.g. the DRB II blocked-reference
# JSON: "the following article and urls: {'title': ...}"), which must never be
# scanned for entity names.
_CLAUSE_END = re.compile(r"[.!?\n{\[]")

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
        # Skip column/attribute specs: "columns including: 'A', 'B'" introduces
        # table headers (attributes), not rows. A spec word (column/field/...)
        # immediately before or after the trigger marks such a list.
        pre = goal[max(0, m.start() - 24):m.start()]
        post = goal[m.end():m.end() + 24]
        if _SPEC_WORDS.search(pre) or _SPEC_WORDS.search(post):
            continue
        rest = goal[m.end():]
        clause_end = _CLAUSE_END.search(rest)
        clause = rest if clause_end is None else rest[: clause_end.start()]
        for p in _PHRASE.finditer(clause):
            phrase = p.group().strip().strip("'\"()").strip()
            # "and"/"or" joins items ("Canada and Spain") — split into parts so
            # each country is its own entity, not one combined item.
            for sub in re.split(r"\s+(?:and|or)\s+", phrase):
                sub = sub.strip()
                if 2 <= len(sub) <= 45 and any(ch.islower() for ch in sub):
                    items.append(sub)
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
    """Repair a plan's aggregate-row coverage_schema (deterministic, v0.2.11+).

    Two independent deterministic guardrails run in sequence:

    1. ``_expand_policy_rows`` — when the brief enumerates >= 2 concrete items
       (countries/models) and the schema carries policy-class attributes, create
       one entity per item scoped to the policy attributes, so per-item policy
       cells are searched instead of crammed into an aggregate row.
    2. ``_expand_cost_study_rows`` (v0.2.12) — when the schema has a
       STUDY-INDEXED cost-table signature ("Model/Study Code" + "Research Source
       (First Author, Year)" + a cost/LCC attribute) but the cost rows are still
       aggregate, expand into per-vehicle-type rows so the search hunts
       individual academic LCA studies (whose exact LCC values DRB II recall
       rubrics require).

    Any plan without these signatures passes through unchanged.
    """
    if not isinstance(plan, dict):
        return plan
    schema = plan.get("coverage_schema")
    if not isinstance(schema, dict):
        return plan
    schema = _expand_policy_rows(schema, goal or "")
    schema = _expand_cost_study_rows(schema)
    return {**plan, "coverage_schema": schema}


def _expand_policy_rows(schema: dict[str, Any], goal: str) -> dict[str, Any]:
    """Policy guardrail: brief-enumerated items → per-item entities (v0.2.11)."""
    attributes = schema.get("attributes")
    entities = schema.get("entities")
    if not isinstance(attributes, list) or not isinstance(entities, list):
        return schema

    policy_attrs = [a for a in attributes if _is_policy_attr(a)]
    if not policy_attrs:
        return schema  # no policy dimension → nothing to expand

    items = [
        it
        for it in _extract_enumerated_items(goal)
        if not _has_entity_named(entities, it)
    ]
    if len(items) < 2:
        return schema

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

    return schema_out


# --- cost study-row expansion (v0.2.12) -------------------------------------

# A STUDY-INDEXED cost table carries a model/study-code attribute, a research
# source (first author, year) attribute, and a cost/LCC attribute. When the plan
# emits that signature but keeps the cost rows aggregate, we expand into
# per-vehicle-type rows so search hunts individual academic LCA studies — the
# ONLY source of the exact per-study LCC values DRB II recall rubrics demand.
_COST_STUDY_SIG = re.compile(r"(?i)(model|vehicle|study).{0,20}(code|name)")
_COST_SOURCE_SIG = re.compile(r"(?i)(research source|first author)")
_COST_VALUE_SIG = re.compile(r"(?i)(lcc|life[\s-]?cycle cost|cost per|price)")


def _expand_cost_study_rows(schema: dict[str, Any]) -> dict[str, Any]:
    """Cost guardrail: aggregate cost rows → per-vehicle-type study rows.

    Fires only when all of: a model/study-code attribute, a research-source
    (first author, year) attribute, and a cost/LCC attribute exist AND the
    non-policy (cost) rows are still aggregate (<= 3 plain entities, i.e. the
    plan did not already decompose). New rows get the cost attributes scoped to
    them plus an academic-LCA search query each.
    """
    attributes = schema.get("attributes")
    entities = schema.get("entities")
    if not isinstance(attributes, list) or not isinstance(entities, list):
        return schema
    names = [str(a.get("name") or "") for a in attributes if isinstance(a, dict)]
    if not any(_COST_STUDY_SIG.search(n) for n in names):
        return schema
    if not any(_COST_SOURCE_SIG.search(n) for n in names):
        return schema
    if not any(_COST_VALUE_SIG.search(n) for n in names):
        return schema

    # Only fire when the cost rows are still aggregate (plain entities count).
    plain = [
        e for e in entities
        if isinstance(e, dict) and e.get("id") and not str(e["id"]).startswith("item_")
    ]
    if len(plain) > 3:
        return schema  # plan already produced per-model rows

    non_policy_ids = sorted({
        str(a.get("id")) for a in attributes
        if isinstance(a, dict) and a.get("id") and not _is_policy_attr(a)
    })
    if not non_policy_ids:
        return schema

    new_rows = [
        {"id": f"cost_{_slug(t)}", "name": t, "kind": "competitor"} for t in _COST_ROW_TYPES
    ]
    scope = dict(schema.get("entity_attributes")) if isinstance(schema.get("entity_attributes"), dict) else {}
    for nr in new_rows:
        if nr["id"] not in scope:
            scope[nr["id"]] = list(non_policy_ids)

    schema = {**schema, "entities": list(entities) + new_rows, "entity_attributes": scope}
    new_queries = [
        {"entity_id": nr["id"], "queries": [f"{t} life cycle cost LCC study"], "source_hints": []}
        for t, nr in zip(_COST_ROW_TYPES, new_rows)
    ]
    existing = schema.get("queries")
    schema["queries"] = list(existing) + new_queries if isinstance(existing, list) else new_queries
    return schema


_COST_ROW_TYPES = [
    "Compact electric vehicle",
    "Mid-size electric vehicle",
    "Mini/urban electric vehicle",
    "SUV electric vehicle",
    "Pickup electric vehicle",
    "Heavy-duty truck electric vehicle",
    "Electric bus",
    "Hybrid electric vehicle (HEV)",
    "Plug-in hybrid electric vehicle (PHEV)",
]


__all__ = ["normalize_plan_output"]
