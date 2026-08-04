"""SOCM Evidence Graph — findings with sources + support/conflict edges.

research-workflow-v1 v0.2.0 F-R26 / ADR 0010 D-S3. Each EvidenceNode is one
(entity, attribute, value, source, confidence) finding extracted by the judge.
Edges record support/conflict relationships between nodes.

Pure domain (G1): no fastapi / aiosqlite / pi_agent / pi_ai. Pydantic only.

Reference (architecture only): SearchOS searchos/socm/evidence.py. Dedup
signature matches SearchOS: (table_id, entity, attribute, body, source) so
corroborating evidence from different pages is kept distinct.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class EvidenceRelation(str, Enum):
    SUPPORT = "support"
    CONFLICT = "conflict"


class EvidenceStatus(str, Enum):
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EvidenceNode(BaseModel):
    """One extracted finding (judge output unit)."""

    id: str
    finding: str = ""               # NL sentence, e.g. "Notion free tier: $0"
    value: str = ""                 # cell-level value alone, e.g. "$0"
    source: str = ""                # URL or tool name
    source_excerpt: str = ""        # verbatim quote anchoring the value
    confidence: float = 0.5
    entity: str = ""
    attribute: str = ""
    table_id: str = ""
    status: EvidenceStatus = EvidenceStatus.ACTIVE
    page_id: str = ""


class EvidenceEdge(BaseModel):
    """A support/conflict relationship between two nodes."""

    from_id: str
    to_id: str
    relation: EvidenceRelation


def _dedup_signature(node: EvidenceNode) -> tuple[str, ...]:
    """Dedup key: same fact + same source = duplicate.

    Entity and attribute matching is case-insensitive, while a missing source
    is treated as node-local evidence rather than as one shared empty source.
    This keeps independent source-less findings instead of collapsing them.
    """
    body = (node.value or node.finding or "").strip().lower()
    source = node.source.strip() or f"<missing-source:{node.id}>"
    return (node.table_id, node.entity.lower(), node.attribute.lower(), body, source)


class EvidenceGraph(BaseModel):
    """Node + edge store for extracted findings."""

    nodes: list[EvidenceNode] = Field(default_factory=list)
    edges: list[EvidenceEdge] = Field(default_factory=list)

    # Lazily-rebuilt dedup index; PrivateAttr keeps it out of serialization
    # (rebuilds from `nodes` on every state reload, matching SearchOS).
    _sig_index: set[tuple[str, ...]] | None = PrivateAttr(default=None)

    def _ensure_index(self) -> set[tuple[str, ...]]:
        if self._sig_index is None:
            self._sig_index = {_dedup_signature(n) for n in self.nodes}
        return self._sig_index

    def add_node(self, node: EvidenceNode) -> bool:
        """Add a node if not a duplicate. Returns True if added, False if dup."""
        sig = _dedup_signature(node)
        index = self._ensure_index()
        if sig in index:
            return False
        index.add(sig)
        self.nodes.append(node)
        return True

    def add_edge(self, edge: EvidenceEdge) -> None:
        """Add an edge (no dedup — edges are append-only audit records)."""
        self.edges.append(edge)

    def get_claims_for(self, entity: str, attribute: str) -> list[EvidenceNode]:
        """All active nodes for an entity×attribute (case-insensitive)."""
        return [
            n
            for n in self.nodes
            if n.entity.lower() == entity.lower()
            and n.attribute.lower() == attribute.lower()
            and n.status == EvidenceStatus.ACTIVE
        ]


    def get_conflicts(self) -> list[tuple[EvidenceNode, EvidenceNode]]:
        """Pairs of nodes connected by a CONFLICT edge."""
        node_map = {n.id: n for n in self.nodes}
        pairs: list[tuple[EvidenceNode, EvidenceNode]] = []
        for edge in self.edges:
            if edge.relation != EvidenceRelation.CONFLICT:
                continue
            a = node_map.get(edge.from_id)
            b = node_map.get(edge.to_id)
            if a is not None and b is not None:
                pairs.append((a, b))
        return pairs

    def node_count(self) -> int:
        return len(self.nodes)

    def to_projection(self) -> dict[str, Any]:
        return {"nodes": self.node_count(), "edges": len(self.edges)}


__all__ = [
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceNode",
    "EvidenceRelation",
    "EvidenceStatus",
]
