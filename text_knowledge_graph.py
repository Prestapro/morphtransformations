"""morphtransformations/text_knowledge_graph.py — Typed text knowledge graph.

Every claim about a text is a typed edge with provenance and a ternary
knowledge status.  No edge is created without an evidence record.

Edge types
----------
REFERS_TO           pronoun/demonstrative → entity (anaphora)
SAME_AS             name variant → canonical entity (strong evidence only)
IS_A                literal classification (not for similes)
COMPARED_TO         simile/metaphor: X как Y, словно Y, будто Y
METAPHORICALLY_AS   metaphorical predication: X — это Y (figurative)
AGENT_OF            entity → event (agentive role)
PATIENT_OF          entity → event
EXPERIENCER_OF      entity → event
RECIPIENT_OF        entity → event
SPEAKER_OF          entity → turn/event
ADDRESSEE_OF        entity/unknown → turn
MENTIONED_IN        entity → scene (mention only, not presence)
PRESENT_IN          entity → scene (confirmed presence)
LOCATED_IN          entity → location
AND / OR / NOT      propositional connectives (between propositions)
IMPLIES             conditional: если P то Q
CAUSES              causal: P потому что Q / из-за P
CONTRASTS           adversative: P но Q / однако
CONDITIONS          conditional scope marker
TEMPORAL            temporal relation between events/scenes

Knowledge status (ternary)
--------------------------
confirmed   explicit structural evidence (speaker label, cast list, etc.)
unknown     insufficient or competing evidence
rejected    explicit counter-evidence

Status: [WORKS] — in-memory, JSON-serialisable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Edge type ────────────────────────────────────────────────────

class EdgeType(str, Enum):
    REFERS_TO         = 'REFERS_TO'
    SAME_AS           = 'SAME_AS'
    IS_A              = 'IS_A'
    COMPARED_TO       = 'COMPARED_TO'
    METAPHORICALLY_AS = 'METAPHORICALLY_AS'
    AGENT_OF          = 'AGENT_OF'
    PATIENT_OF        = 'PATIENT_OF'
    EXPERIENCER_OF    = 'EXPERIENCER_OF'
    RECIPIENT_OF      = 'RECIPIENT_OF'
    BENEFICIARY_OF    = 'BENEFICIARY_OF'
    STIMULUS_OF       = 'STIMULUS_OF'
    SPEAKER_OF        = 'SPEAKER_OF'
    ADDRESSEE_OF      = 'ADDRESSEE_OF'
    MENTIONED_IN      = 'MENTIONED_IN'
    PRESENT_IN        = 'PRESENT_IN'
    LOCATED_IN        = 'LOCATED_IN'
    AND               = 'AND'
    OR                = 'OR'
    NOT               = 'NOT'
    IMPLIES           = 'IMPLIES'
    CAUSES            = 'CAUSES'
    CONTRASTS         = 'CONTRASTS'
    CONDITIONS        = 'CONDITIONS'
    TEMPORAL          = 'TEMPORAL'


# ── Knowledge status ─────────────────────────────────────────────

class KnowledgeStatus(str, Enum):
    CONFIRMED = 'confirmed'
    UNKNOWN   = 'unknown'
    REJECTED  = 'rejected'


# ── Evidence record ──────────────────────────────────────────────

@dataclass
class Evidence:
    """One piece of evidence supporting an edge."""
    source_module: str          # e.g. 'speaker_label', 'anaphora', 'event_role'
    token_range: list[int]      # [start, end] inclusive
    confidence: float           # 0.0–1.0
    detail: str = ''            # human-readable note

    def to_dict(self) -> dict:
        return {
            'source_module': self.source_module,
            'token_range': self.token_range,
            'confidence': round(self.confidence, 3),
            'detail': self.detail,
        }


# ── Node ─────────────────────────────────────────────────────────

@dataclass
class TKGNode:
    """A node in the text knowledge graph.

    Nodes represent entities, events, scenes, turns, propositions or
    unknown referents.  The ``node_id`` is stable within one analysis.
    """
    node_id: str
    node_type: str          # 'entity', 'event', 'scene', 'turn', 'proposition', 'unknown'
    label: str              # human-readable surface form or canonical name
    token_range: list[int] | None = None
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {
            'node_id': self.node_id,
            'node_type': self.node_type,
            'label': self.label,
        }
        if self.token_range is not None:
            d['token_range'] = self.token_range
        if self.attributes:
            d['attributes'] = self.attributes
        return d


# ── Edge ─────────────────────────────────────────────────────────

@dataclass
class TKGEdge:
    """A typed, evidence-backed edge between two nodes."""
    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    knowledge_status: KnowledgeStatus
    evidence: list[Evidence] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)  # competing targets when unknown
    scope: str | None = None    # node_id of the scope (scene, proposition, etc.)

    @property
    def confidence(self) -> float:
        if not self.evidence:
            return 0.0
        return max(e.confidence for e in self.evidence)

    def to_dict(self) -> dict:
        d: dict = {
            'edge_id': self.edge_id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'edge_type': self.edge_type.value,
            'knowledge_status': self.knowledge_status.value,
            'confidence': round(self.confidence, 3),
            'evidence': [e.to_dict() for e in self.evidence],
        }
        if self.candidates:
            d['candidates'] = self.candidates
        if self.scope:
            d['scope'] = self.scope
        return d


# ── Graph ────────────────────────────────────────────────────────

class TextKnowledgeGraph:
    """In-memory typed knowledge graph for one text analysis.

    All mutations go through ``add_node`` / ``add_edge`` so that
    invariants (no edge without evidence, no SAME_AS without strong
    evidence) are enforced in one place.
    """

    # Minimum confidence required for SAME_AS edges.
    SAME_AS_MIN_CONFIDENCE = 0.85

    def __init__(self) -> None:
        self._nodes: dict[str, TKGNode] = {}
        self._edges: dict[str, TKGEdge] = {}
        self._edge_counter = 0
        self._node_counter = 0

    # ── Node management ──────────────────────────────────────────

    def add_node(self, node_type: str, label: str,
                 token_range: list[int] | None = None,
                 attributes: dict | None = None,
                 node_id: str | None = None) -> TKGNode:
        if node_id and node_id in self._nodes:
            return self._nodes[node_id]
        if node_id is None:
            self._node_counter += 1
            node_id = f'n{self._node_counter}'
        node = TKGNode(
            node_id=node_id,
            node_type=node_type,
            label=label,
            token_range=token_range,
            attributes=attributes or {},
        )
        self._nodes[node_id] = node
        return node

    def get_or_create_entity(self, entity_id: str, label: str,
                             token_range: list[int] | None = None) -> TKGNode:
        """Return existing entity node or create one."""
        nid = f'entity:{entity_id}'
        if nid in self._nodes:
            return self._nodes[nid]
        return self.add_node('entity', label, token_range=token_range, node_id=nid)

    def get_or_create_scene(self, scene_id: str,
                            token_range: list[int] | None = None) -> TKGNode:
        nid = f'scene:{scene_id}'
        if nid in self._nodes:
            return self._nodes[nid]
        return self.add_node('scene', scene_id, token_range=token_range, node_id=nid)

    def get_or_create_turn(self, turn_id: str,
                           token_range: list[int] | None = None) -> TKGNode:
        nid = f'turn:{turn_id}'
        if nid in self._nodes:
            return self._nodes[nid]
        return self.add_node('turn', turn_id, token_range=token_range, node_id=nid)

    def get_or_create_event(self, event_id: str, label: str,
                            token_range: list[int] | None = None) -> TKGNode:
        nid = f'event:{event_id}'
        if nid in self._nodes:
            return self._nodes[nid]
        return self.add_node('event', label, token_range=token_range, node_id=nid)

    # ── Edge management ──────────────────────────────────────────

    def add_edge(self, source_id: str, target_id: str,
                 edge_type: EdgeType,
                 evidence: list[Evidence],
                 knowledge_status: KnowledgeStatus | None = None,
                 candidates: list[str] | None = None,
                 scope: str | None = None) -> TKGEdge | None:
        """Add a typed edge.  Returns None if invariants are violated."""
        if not evidence:
            return None  # no edge without evidence

        # SAME_AS requires strong evidence
        if edge_type == EdgeType.SAME_AS:
            max_conf = max(e.confidence for e in evidence)
            if max_conf < self.SAME_AS_MIN_CONFIDENCE:
                return None

        # Derive status from evidence if not supplied
        if knowledge_status is None:
            max_conf = max(e.confidence for e in evidence)
            if max_conf >= 0.85:
                knowledge_status = KnowledgeStatus.CONFIRMED
            elif max_conf >= 0.5:
                knowledge_status = KnowledgeStatus.UNKNOWN
            else:
                knowledge_status = KnowledgeStatus.UNKNOWN

        self._edge_counter += 1
        edge_id = f'e{self._edge_counter}'
        edge = TKGEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            knowledge_status=knowledge_status,
            evidence=evidence,
            candidates=candidates or [],
            scope=scope,
        )
        self._edges[edge_id] = edge
        return edge

    # ── Simile / comparison guard ────────────────────────────────

    def add_comparison(self, source_id: str, target_id: str,
                       evidence: list[Evidence],
                       is_metaphor: bool = False) -> TKGEdge | None:
        """Add COMPARED_TO or METAPHORICALLY_AS — never IS_A or SAME_AS."""
        etype = EdgeType.METAPHORICALLY_AS if is_metaphor else EdgeType.COMPARED_TO
        return self.add_edge(source_id, target_id, etype, evidence,
                             knowledge_status=KnowledgeStatus.UNKNOWN)

    # ── Addressee with discourse search ─────────────────────────

    def add_addressee(self, turn_id: str, entity_id: str | None,
                      evidence: list[Evidence],
                      candidates: list[str] | None = None) -> TKGEdge | None:
        """Add ADDRESSEE_OF edge.

        When entity_id is None (no confirmed referent), creates an
        UNKNOWN edge to an explicit 'unknown' node with candidates.
        """
        turn_nid = f'turn:{turn_id}'
        if entity_id:
            target_nid = f'entity:{entity_id}'
            status = KnowledgeStatus.CONFIRMED if (
                evidence and max(e.confidence for e in evidence) >= 0.85
            ) else KnowledgeStatus.UNKNOWN
        else:
            target_nid = 'unknown:addressee'
            if target_nid not in self._nodes:
                self.add_node('unknown', 'Unknown addressee', node_id=target_nid)
            status = KnowledgeStatus.UNKNOWN
        return self.add_edge(turn_nid, target_nid, EdgeType.ADDRESSEE_OF,
                             evidence, knowledge_status=status,
                             candidates=candidates or [])

    # ── Serialisation ────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            'nodes': [n.to_dict() for n in self._nodes.values()],
            'edges': [e.to_dict() for e in self._edges.values()],
            'stats': {
                'n_nodes': len(self._nodes),
                'n_edges': len(self._edges),
                'confirmed': sum(1 for e in self._edges.values()
                                 if e.knowledge_status == KnowledgeStatus.CONFIRMED),
                'unknown': sum(1 for e in self._edges.values()
                               if e.knowledge_status == KnowledgeStatus.UNKNOWN),
                'rejected': sum(1 for e in self._edges.values()
                                if e.knowledge_status == KnowledgeStatus.REJECTED),
            },
        }

    # ── Ambiguity metrics ────────────────────────────────────────

    def compute_ambiguity(self) -> dict:
        """Compute per-edge-type ambiguity counts.

        An edge is ambiguous when knowledge_status == unknown and it has
        competing candidates.  This is the foundation for the Ambiguity
        timeline track.
        """
        import math
        ambiguous_edges = []
        for edge in self._edges.values():
            if edge.knowledge_status == KnowledgeStatus.UNKNOWN:
                n_candidates = max(len(edge.candidates), 1)
                h = round(math.log2(n_candidates + 1), 3)
                ambiguous_edges.append({
                    'edge_id': edge.edge_id,
                    'edge_type': edge.edge_type.value,
                    'source_id': edge.source_id,
                    'target_id': edge.target_id,
                    'n_candidates': n_candidates,
                    'H': h,
                    'evidence': [ev.to_dict() for ev in edge.evidence],
                })
        total = len(self._edges)
        ambiguous = len(ambiguous_edges)
        return {
            'total_edges': total,
            'ambiguous_edges': ambiguous,
            'ambiguity_ratio': round(ambiguous / total, 3) if total else 0.0,
            'details': ambiguous_edges,
        }
