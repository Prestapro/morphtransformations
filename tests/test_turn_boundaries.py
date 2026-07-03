"""Regression test corpus for Spectrum turn boundary detection.

Ground truth for 3 text formats:
- Drama: SPEAKER\\nText... (Горе от ума style)
- Prose EM-dash: — speech — attribution verb Name.
- Mixed: both formats in one text

Tests verify:
- Correct number of turns detected
- Speaker names correctly extracted
- Entity IDs canonicalized
- Pronoun coreference resolved
- Speech act detection (question, command, rhetorical)
- Embedded quote sub-classification
"""
import pytest
import requests
import json
import time
import subprocess
import signal
import os
import sys

API_URL = "http://localhost:8001/api/entropy_map"

# ============================================================
# Test data: (text, expected)
# ============================================================

DRAMA_TEXT = """ФАМУСОВ
Что за оказия! Молчалин, ты, брат?

Молчалин
Я-с.

Фамусов
Ну, выкинул ты штуку!"""

DRAMA_EXPECTED = {
    'turn_count': 3,
    'speakers': ['Фамусов', 'Молчалин', 'Фамусов'],
    'entity_ids': ['фамусов', 'молчалин', 'фамусов'],
    'pronoun_refs': {'ты': 'Молчалин'},
}

PROSE_EM_TEXT = """— Ты куда идёшь? — спросил Иван.
— Домой, — ответила Маша. — А ты?
— Я ещё побуду здесь.
Она повернулась и ушла."""

PROSE_EM_EXPECTED = {
    'min_speakers': 2,
    'dialogue_format': 'prose_em',
    'has_speaker_segments': True,
}

RHETORICAL_TEXT = """Фамусов
Разве ты не видишь? Неужели он слеп?

Чацкий
Где же правда? Надо поискать.

Молчалин
Ты откуда приехал?"""

RHETORICAL_EXPECTED = {
    'T0_rhetorical': True,  # 'разве' marker
    'T1_rhetorical': True,  # self-response
    'T2_rhetorical': False, # plain question
}

QUOTE_TEXT = """Фамусов
Читал ли ты роман «Евгений Онегин»? Он сказал: «Пойдём домой». Этот так называемый «подвиг» меня не впечатлил."""

QUOTE_EXPECTED = {
    'quote_types': ['title', 'embedded_speech', 'ironic'],
}

COREF_TEXT = """Фамусов
Где София? Она ведь обещала.

Чацкий
Она уехала давно."""

COREF_EXPECTED = {
    'pronoun_refs': [
        ('Она', 'София', 'Фамусов'),
        ('Она', 'София', 'Чацкий'),
    ],
}

ENTITY_ID_TEXT = """ФАМУСОВ
Барин, да.

Фамусов
Ну что ж?"""

ENTITY_ID_EXPECTED = {
    'entity_ids': ['фамусов', 'фамусов'],  # same entity_id for CAPS and Title
}


# ============================================================
# Helpers
# ============================================================

def _api(text: str) -> dict:
    """Call the API and return response JSON."""
    resp = requests.post(API_URL, json={"text": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ============================================================
# Tests
# ============================================================

class TestDramaTurns:
    """Drama format: SPEAKER\\nText..."""
    
    def test_turn_count(self):
        d = _api(DRAMA_TEXT)
        turns = d.get('dialogue_turns', [])
        assert len(turns) == DRAMA_EXPECTED['turn_count'], \
            f"Expected {DRAMA_EXPECTED['turn_count']} turns, got {len(turns)}"
    
    def test_speaker_names(self):
        d = _api(DRAMA_TEXT)
        turns = d.get('dialogue_turns', [])
        speakers = [t['speaker'] for t in turns]
        assert speakers == DRAMA_EXPECTED['speakers'], \
            f"Expected {DRAMA_EXPECTED['speakers']}, got {speakers}"
    
    def test_entity_ids(self):
        d = _api(DRAMA_TEXT)
        turns = d.get('dialogue_turns', [])
        eids = [t.get('entity_id', '') for t in turns]
        assert eids == DRAMA_EXPECTED['entity_ids'], \
            f"Expected {DRAMA_EXPECTED['entity_ids']}, got {eids}"
    
    def test_pronoun_ref(self):
        d = _api(DRAMA_TEXT)
        refs = {}
        for t in d['data']:
            if t.get('pronoun_ref'):
                refs[t['word']] = t['pronoun_ref']
        for pron, expected_ref in DRAMA_EXPECTED['pronoun_refs'].items():
            assert pron in refs, f"Pronoun '{pron}' not resolved"
            assert refs[pron] == expected_ref, \
                f"'{pron}' → '{refs[pron]}', expected '{expected_ref}'"


class TestProseEM:
    """Prose with em-dash speech markers."""
    
    def test_dialogue_format(self):
        d = _api(PROSE_EM_TEXT)
        assert d.get('dialogue_format') == PROSE_EM_EXPECTED['dialogue_format'], \
            f"Expected 'prose_em', got {d.get('dialogue_format')}"
    
    def test_speaker_segments(self):
        d = _api(PROSE_EM_TEXT)
        speaker_segs = [s for s in d.get('segments', []) if s['type'] == 'speaker']
        assert len(speaker_segs) >= PROSE_EM_EXPECTED['min_speakers'], \
            f"Expected >= {PROSE_EM_EXPECTED['min_speakers']} speaker segments, got {len(speaker_segs)}"


class TestRhetoricalQuestions:
    """Rhetorical vs plain question detection."""
    
    def test_marker_rhetorical(self):
        d = _api(RHETORICAL_TEXT)
        turns = d.get('dialogue_turns', [])
        acts_0 = turns[0].get('speech_acts', {})
        assert 'rhetorical_question' in acts_0, \
            f"T0 should be rhetorical (marker 'разве'), got {acts_0}"
        assert acts_0['rhetorical_question'] >= 0.85
    
    def test_self_response_rhetorical(self):
        d = _api(RHETORICAL_TEXT)
        turns = d.get('dialogue_turns', [])
        acts_1 = turns[1].get('speech_acts', {})
        assert 'rhetorical_question' in acts_1, \
            f"T1 should be rhetorical (self-response), got {acts_1}"
        assert acts_1['rhetorical_question'] >= 0.60
    
    def test_plain_question(self):
        d = _api(RHETORICAL_TEXT)
        turns = d.get('dialogue_turns', [])
        acts_2 = turns[2].get('speech_acts', {})
        assert 'rhetorical_question' not in acts_2, \
            f"T2 should NOT be rhetorical, got {acts_2}"


class TestEmbeddedQuotes:
    """Embedded quote sub-classification."""
    
    def test_quote_types(self):
        d = _api(QUOTE_TEXT)
        turns = d.get('dialogue_turns', [])
        assert len(turns) > 0
        segments = turns[0].get('segments', [])
        seg_types = [s['type'] for s in segments 
                     if s['type'] not in ('dialogue', 'speaker_label')]
        assert 'title' in seg_types, f"Expected 'title' quote, got {seg_types}"
        assert 'embedded_speech' in seg_types, f"Expected 'embedded_speech', got {seg_types}"
        assert 'ironic' in seg_types, f"Expected 'ironic', got {seg_types}"


class TestCoreference:
    """Cross-turn pronoun coreference."""
    
    def test_she_resolves_to_sofia(self):
        d = _api(COREF_TEXT)
        refs = []
        for t in d['data']:
            if t.get('pronoun_ref'):
                refs.append((t['word'], t['pronoun_ref'], t.get('speaker', '')))
        
        for pron, target, speaker in COREF_EXPECTED['pronoun_refs']:
            found = any(r[0] == pron and r[1] == target and r[2] == speaker 
                       for r in refs)
            assert found, \
                f"Expected '{pron}' → '{target}' in {speaker}'s speech, got {refs}"


class TestEntityID:
    """Entity ID normalization (CAPS vs Title case)."""
    
    def test_same_entity_id(self):
        d = _api(ENTITY_ID_TEXT)
        turns = d.get('dialogue_turns', [])
        eids = [t.get('entity_id', '') for t in turns]
        assert eids == ENTITY_ID_EXPECTED['entity_ids'], \
            f"Expected {ENTITY_ID_EXPECTED['entity_ids']}, got {eids}"


class TestSchemaVersion:
    """API schema versioning."""
    
    def test_schema_version(self):
        d = _api("Тест.")
        assert d.get('schema_version') == 4, \
            f"Expected schema_version=4, got {d.get('schema_version')}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
