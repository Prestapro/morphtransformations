"""Regression tests for Spectrum predicate-valency role evidence."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import build_text_knowledge_graph, extract_observable_event_roles


def _token(word, entity_id='', clean=''):
    return {'word': word, 'entity_id': entity_id, 'clean': clean}


def test_helping_dative_uses_beneficiary_frame_role():
    events = extract_observable_event_roles([
        _token('Петя', 'петя', 'Петя'),
        _token('помогает'),
        _token('Маше', 'маша', 'Маша'),
        _token('.'),
    ])

    assert events[0]['predicate'] == 'помогать'
    assert events[0]['verb_frame'] == 'AGENT(nomn) BENEFICIARY(datv) CONTENT(INF)'
    assert events[0]['roles'][1]['role'] == 'beneficiary'
    assert events[0]['roles'][1]['source'] == 'verb_frame'
    assert events[0]['incomplete_event'] is False

    graph = build_text_knowledge_graph([], [], [], events, [])
    beneficiary_edges = [
        edge for edge in graph.to_dict()['edges']
        if edge['edge_type'] == 'BENEFICIARY_OF'
    ]
    assert len(beneficiary_edges) == 1
    assert beneficiary_edges[0]['source_id'] == 'entity:маша'
    assert beneficiary_edges[0]['evidence'][0]['source_module'] == 'event_role:verb_frame'


def test_incomplete_transfer_exposes_missing_obligatory_roles():
    events = extract_observable_event_roles([
        _token('Петя', 'петя', 'Петя'),
        _token('дал'),
        _token('Маше', 'маша', 'Маша'),
        _token('.'),
    ])

    assert events[0]['predicate'] == 'дать'
    assert events[0]['incomplete_event'] is True
    assert events[0]['missing_roles'] == ['PATIENT']
