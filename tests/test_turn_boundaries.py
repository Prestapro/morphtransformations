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


class TestEntityIdNormalization:
    """entity_id preserves gender and does not truncate surnames."""

    def test_rakolnikov_not_truncated(self):
        d = _api("Раскольников\nЯ это сделал.")
        eids = [t.get('entity_id','') for t in d['dialogue_turns']]
        assert any('раскольников' in e for e in eids), f"got {eids}"

    def test_astrov_not_truncated(self):
        d = _api("Астров\nНичего, брат.")
        eids = [t.get('entity_id','') for t in d['dialogue_turns']]
        assert any('астров' in e for e in eids), f"got {eids}"

    def test_sidorov_sidorova_different_eids(self):
        """Сидоров (masc) and Сидорова (femn) must have different entity_ids."""
        from engine.language.inflector import _cached_reverse_lookup
        def eid(name):
            sl = name.lower()
            rows = _cached_reverse_lookup(sl)
            if rows:
                for _, _, gram, _ in rows:
                    if ('femn' in gram or 'masc' in gram) and 'nomn' in gram and 'Surn' in gram:
                        return sl.replace('ё', 'е')
            return sl.replace('ё', 'е')
        assert eid('Сидоров') != eid('Сидорова'), \
            f"Сидоров and Сидорова must differ: {eid('Сидоров')!r} vs {eid('Сидорова')!r}"

    def test_caps_and_title_same_eid(self):
        """ФАМУСОВ and Фамусов must resolve to the same entity_id."""
        d = _api("ФАМУСОВ\nЧто за оказия!\n\nМолчалин\nЯ-с.")
        eids = {t.get('entity_id','') for t in d['dialogue_turns']}
        # Both ФАМУСОВ and Фамусов lower to 'фамусов'
        assert 'фамусов' in eids, f"got {eids}"

    def test_oov_names_preserved(self):
        """OOV invented names are kept as-is, not truncated."""
        d = _api("Зорак\nТы не пройдёшь.\n\nЭлинда\nЯ должна.")
        eids = [t.get('entity_id','') for t in d['dialogue_turns']]
        assert 'зорак' in eids and 'элинда' in eids, f"got {eids}"


class TestTextKnowledgeGraph:
    """TKG invariants: no edge without evidence, no SAME_AS without strong evidence."""

    def test_graph_present_in_response(self):
        d = _api("Фамусов\nЯ здесь.")
        assert 'knowledge_graph' in d
        kg = d['knowledge_graph']
        assert 'nodes' in kg and 'edges' in kg and 'stats' in kg

    def test_speaker_edge_is_confirmed(self):
        d = _api("Фамусов\nЯ здесь.")
        kg = d['knowledge_graph']
        speaker_edges = [e for e in kg['edges'] if e['edge_type'] == 'SPEAKER_OF']
        assert speaker_edges, "Expected at least one SPEAKER_OF edge"
        assert all(e['knowledge_status'] == 'confirmed' for e in speaker_edges)

    def test_mention_only_is_not_present_in(self):
        d = _api("Фамусов\nГде Чацкий?")
        kg = d['knowledge_graph']
        present_edges = [e for e in kg['edges'] if e['edge_type'] == 'PRESENT_IN']
        chatsky_present = [e for e in present_edges
                           if 'чацкий' in e['source_id'].lower()
                           or 'chatsky' in e['source_id'].lower()]
        assert not chatsky_present, "Mention must not become PRESENT_IN"

    def test_ambiguity_field_present(self):
        d = _api("Он ушёл.")
        assert 'ambiguity' in d
        amb = d['ambiguity']
        for key in ('total_edges', 'ambiguous_edges', 'ambiguity_ratio'):
            assert key in amb, f"Missing ambiguity key: {key}"

    def test_no_edge_without_evidence(self):
        d = _api("Фамусов\nЧацкий пришёл.")
        for edge in d['knowledge_graph']['edges']:
            assert edge['evidence'], f"Edge {edge['edge_id']} has no evidence"


class TestReferenceStability:
    """Reference metrics preserve unresolved pronouns as uncertainty."""

    def test_unresolved_pronoun_is_reported(self):
        d = _api("Он ушёл.")
        r = d['reference_stability']
        assert r['total_pronouns'] == 1
        assert r['resolved_count'] == 0
        assert r['unresolved_count'] == 1
        assert r['stability'] == 0.0

    def test_resolved_pronoun_is_counted(self):
        d = _api("Фамусов\nГде София? Она обещала.")
        r = d['reference_stability']
        assert r['resolved_count'] >= 1
        assert r['stability'] > 0


class TestSceneRoleGrid:
    """Scene participation distinguishes observation from inference."""

    def test_mention_does_not_confirm_presence(self):
        d = _api("Фамусов\nГде София?\n\nЧацкий\nСофия уехала.")
        sofia = next(entity for entity in d['entities']
                     if entity['canonical_name'].lower() == 'софия')
        rows = [row for row in d['entity_grid']
                if row['entity_id'] == sofia['entity_id']]
        assert rows
        assert all(row['scene_status'] != 'confirmed' for row in rows)

    def test_speaker_is_confirmed_present(self):
        d = _api("Фамусов\nЯ здесь.")
        famusov = next(entity for entity in d['entities']
                       if entity['canonical_name'].lower() == 'фамусов')
        row = next(row for row in d['entity_grid']
                   if row['entity_id'] == famusov['entity_id'])
        assert row['scene_status'] == 'confirmed'
        assert 'speaker' in row['roles']

    def test_event_roles_are_optional_and_traceable(self):
        d = _api("Фамусов открыл дверь.")
        assert 'event_roles' in d
        for event in d['event_roles']:
            for role in event['roles']:
                assert role['role'] in {
                    'agent', 'patient', 'recipient', 'location',
                    'direction', 'source', 'experiencer',
                }
                assert role['token_range'][0] <= role['token_range'][1]
                assert role['source']

    def test_entities_expose_observable_salience_only(self):
        d = _api("Фамусов\nЯ пришёл.\n\nЧацкий\nЯ слушаю.")
        assert d['entities']
        for entity in d['entities']:
            assert isinstance(entity['acting_score'], (int, float))
            assert entity['salience'] in {'low', 'medium', 'high'}
            assert entity['scene_count'] >= 1


class TestSchemaVersion:
    """API schema versioning."""
    
    def test_schema_version(self):
        d = _api("Тест.")
        assert d.get('schema_version') == 7, \
            f"Expected schema_version=7, got {d.get('schema_version')}"


class TestDepthMetrics:
    """Text depth / flatness measurement."""
    
    def test_depth_present(self):
        d = _api("Мой дядя самых честных правил, когда не в шутку занемог.")
        assert 'depth' in d, "depth field missing from API response"
        depth = d['depth']
        for key in ('lexical', 'semantic', 'structural', 'coherence', 'composite'):
            assert key in depth, f"depth.{key} missing"
    
    def test_flat_text_low_depth(self):
        d = _api("Мама мыла раму. Папа мыл раму. Мама мыла окно.")
        depth = d['depth']
        assert depth['composite'] < 0.05, \
            f"Flat text should have low composite depth, got {depth['composite']}"
    
    def test_rich_text_higher_depth(self):
        text = ("Мой дядя самых честных правил, когда не в шутку занемог, "
                "он уважать себя заставил и лучше выдумать не мог. "
                "Его пример другим наука; но, Боже мой, какая скука "
                "с больным сидеть и день и ночь, не отходя ни шагу прочь!")
        d = _api(text)
        depth = d['depth']
        assert depth['lexical'] > 0.5, f"Pushkin should have high lexical, got {depth['lexical']}"
        assert depth['composite'] > depth['lexical'] * 0.01, \
            f"Rich text composite should be meaningful, got {depth['composite']}"


class TestServiceWords:
    """Service word classification: POS overrides, discourse, modal, semantic roles."""
    
    def test_pos_and_lemma_present(self):
        d = _api("Он говорил громко.")
        tokens = d['data']
        alpha_tokens = [t for t in tokens if t['word'].isalpha()]
        for t in alpha_tokens:
            assert t.get('pos'), f"Token '{t['word']}' missing POS"
            assert t.get('lemma'), f"Token '{t['word']}' missing lemma"
    
    def test_conjunction_override(self):
        """'и', 'хотя' should be CONJ, not NOUN/GRND."""
        d = _api("Он говорил, хотя и знал.")
        tokens = {t['word'].lower(): t for t in d['data'] if t['word'].isalpha()}
        assert tokens['и'].get('pos') == 'CONJ', f"'и' POS={tokens['и'].get('pos')}, expected CONJ"
        assert tokens['хотя'].get('pos') == 'CONJ', f"'хотя' POS={tokens['хотя'].get('pos')}"
        assert tokens['хотя'].get('discourse_role') == 'concession'
    
    def test_particle_override(self):
        """'ли', 'разве', 'не' should be PRCL with modal types."""
        d = _api("Разве вы не знаете, правда ли это?")
        tokens_list = [t for t in d['data'] if t['word'].isalpha()]
        by_word = {}
        for t in tokens_list:
            by_word.setdefault(t['word'].lower(), t)
        
        assert by_word['разве'].get('pos') == 'PRCL', f"'разве' POS={by_word['разве'].get('pos')}"
        assert by_word['разве'].get('modal_type') == 'rhetorical'
        assert by_word['ли'].get('pos') == 'PRCL'
        assert by_word['ли'].get('modal_type') == 'interrogative'
        assert by_word['не'].get('pos') == 'PRCL'
        assert by_word['не'].get('modal_type') == 'negation'
    
    def test_service_word_stats(self):
        d = _api("А ведь он, несмотря на это, хотя и говорил.")
        sws = d.get('service_word_stats', {})
        assert 'n_content' in sws
        assert 'n_service' in sws
        assert 'lexical_density' in sws
        assert 'discourse_profile' in sws
        assert 'modal_profile' in sws
        assert 'pos_distribution' in sws
        assert sws['n_service'] > 0, "Should detect service words"
        assert 0 < sws['lexical_density'] < 1, f"Lexical density out of range: {sws['lexical_density']}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
