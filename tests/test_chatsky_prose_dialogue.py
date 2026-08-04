"""Regression for Russian prose dialogue attribution in the Spectrum endpoint.

Calls the analysis function directly (same convention as
test_event_role_valency.py) so no external server is required.
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(REPO_ROOT))

from app import TensionMapRequest, entropy_map  # noqa: E402

FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'narrative' / 'chatsky_dialogue.txt'


def _analyze(text: str) -> dict:
    return asyncio.run(entropy_map(TensionMapRequest(text=text)))


@pytest.fixture(scope='module')
def chatsky() -> dict:
    return _analyze(FIXTURE.read_text(encoding='utf-8'))


def _words(result: dict, start: int, end: int) -> list:
    return [token['word'] for token in result['data'][start:end + 1]]


class TestProseTurnBounds:
    def test_first_turn_is_sofya_speech_only(self, chatsky):
        turn = chatsky['dialogue_turns'][0]
        assert turn['speaker'] == 'Софья'
        assert (turn['start_token'], turn['end_token']) == (34, 41)
        assert _words(chatsky, turn['start_token'], turn['end_token']) == [
            '.', '—', 'Кто', 'там', 'ходит', 'в', 'такую', 'рань',
        ]

    def test_author_clause_is_not_a_turn(self, chatsky):
        # '— спросила Софья, не оборачиваясь.' occupies tokens 43..49.
        assert _words(chatsky, 44, 45) == ['спросила', 'Софья']
        owners = [
            turn for turn in chatsky['dialogue_turns']
            if turn['start_token'] <= 44 <= turn['end_token']
        ]
        assert owners == []

    def test_turns_are_finite_and_ordered(self, chatsky):
        turns = chatsky['dialogue_turns']
        assert turns
        previous_end = -1
        for turn in turns:
            assert isinstance(turn['start_token'], int)
            assert isinstance(turn['end_token'], int)
            assert turn['start_token'] <= turn['end_token'] < len(chatsky['data'])
            assert turn['start_token'] > previous_end
            previous_end = turn['end_token']

    def test_attribution_verb_broshl_resolves_to_chatsky(self, chatsky):
        assert 'Чацкий' in {turn['speaker'] for turn in chatsky['dialogue_turns']}

    def test_no_speaker_owns_the_document(self, chatsky):
        total = len(chatsky['data'])
        owned = {}
        for turn in chatsky['dialogue_turns']:
            speaker = turn['speaker']
            if speaker:
                owned[speaker] = owned.get(speaker, 0) + (
                    turn['end_token'] - turn['start_token'] + 1
                )
        assert owned
        assert max(owned.values()) < total // 2
        assert owned.get('Лиза', 0) < 100

    def test_turn_confidence_is_bounded(self, chatsky):
        for turn in chatsky['dialogue_turns']:
            assert 0.0 <= turn['confidence'] <= 1.0
            if not turn['speaker']:
                assert turn['confidence'] == 0.0

    def test_unattributed_turn_stays_bounded(self, chatsky):
        anonymous = [t for t in chatsky['dialogue_turns'] if not t['speaker']]
        assert anonymous
        for turn in anonymous:
            assert turn['end_token'] < len(chatsky['data']) - 1

    def test_empty_text_yields_no_turns(self):
        result = _analyze('')
        assert result['data'] == []
        assert result['meta']['token_count'] == 0


class TestEntityIdentity:
    def test_molchalin_is_registered(self, chatsky):
        ids = {entity['entity_id'] for entity in chatsky['entities']}
        assert any('молчалин' in entity_id for entity_id in ids)

    def test_entity_id_never_carries_another_name(self, chatsky):
        by_id = {e['entity_id']: e['canonical_name'] for e in chatsky['entities']}
        assert 'Чацкий' not in by_id.get('лиза', '')
        assert by_id.get('лиза') == 'Лиза'
        assert by_id.get('софья') == 'Софья'

    def test_function_words_are_not_entities(self, chatsky):
        ids = {entity['entity_id'] for entity in chatsky['entities']}
        assert not ids & {'role:в', 'role:у', 'role:на', 'role:о', 'role:и'}
        for token in chatsky['data']:
            if token.get('service_type') in ('preposition', 'conjunction', 'particle'):
                assert not token.get('entity_id')


class TestRoleEvidence:
    def test_role_confidence_is_evidence_derived(self, chatsky):
        confidences = [
            role['confidence']
            for event in chatsky['event_roles']
            for role in event['roles']
        ]
        assert confidences
        assert all(0.0 <= value <= 1.0 for value in confidences)
        assert set(confidences) != {1.0}

    def test_source_role_requires_a_verb_frame(self, chatsky):
        for event in chatsky['event_roles']:
            for role in event['roles']:
                if role['role'] == 'source':
                    assert role['source'] == 'verb_frame'
