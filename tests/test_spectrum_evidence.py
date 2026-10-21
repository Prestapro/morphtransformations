"""Regression and integration checks for Spectrum's evidence adapters."""
import re
import pytest
from engine.parsing.dep_parser import DepParser
from speech_attribution import analyze_speech_structure, narrator_event_role_events
from spectrum_evidence import attach_epistemic_evidence, analyze_style, annotate_source_referents


def tokens(text):
    from engine.language.inflector import analyze
    rows = []
    for m in re.finditer(r'[\w-]+|[^\w\s]', text):
        p = analyze(m.group())[0] if m.group()[0].isalpha() else None
        rows.append(dict(word=m.group(), clean=m.group(),
            pos=p.pos if p else 'PUNCT', lemma=p.lemma if p else m.group(),
            char_start=m.start(), char_end=m.end()))
    return rows


def test_non_reporting_complement_cannot_add_maria_to_sleeping_event():
    text = 'Иван не спал, что Мария пришла.'
    d = analyze_speech_structure(text, tokens(text), parser=DepParser())
    assert not d['speech_claims']
    world = narrator_event_role_events(d['event_roles'])
    assert not any(r['name'] == 'Мария' for e in world if e['predicate'] == 'спать'
                   for r in e['roles'])
    maria = next(r for e in d['event_roles'] for r in e['roles'] if r['name'] == 'Мария')
    assert maria['epistemic']['truth_kind'] == 'refuted'
    assert maria['scope'] == 'unresolved_clause'


def test_unification_retains_unknowns_without_probabilities():
    text = 'Большой дом стоял. Зззквант ушёл.'
    ts = tokens(text)
    d = analyze_speech_structure(text, ts, parser=DepParser())
    assert d['morph_unification']
    assert sum(x['constraints_applied'] for x in d['morph_unification']) > 0
    for row in ts:
        if row.get('morph_readings'):
            assert row['morph_readings']['candidates']
            assert all(p['probability'] is None for p in row['morph_readings']['candidates'])
    assert next(r for r in ts if r['word'] == 'Зззквант')['morph_readings']['candidates']


def test_explicit_opinion_is_discounted_but_missing_trust_stays_unknown():
    claims = [{'claim_id': 'c', 'source_name': 'Иван', 'source_entity_id': 'ivan'}]
    attach_epistemic_evidence(claims, [])
    assert claims[0]['epistemic']['source_trust'] is None
    assert claims[0]['epistemic']['probability'] is None
    attach_epistemic_evidence(claims, [], {'ivan': dict(belief=.6, disbelief=.1,
        uncertainty=.3, base_rate=.2, trust=.5)})
    assert claims[0]['epistemic']['support'] == pytest.approx(dict(belief=.3, disbelief=.05, uncertainty=.65))
    assert claims[0]['epistemic']['truth_kind'] == 'assumed'


def test_style_is_measured_and_intonation_is_unknown():
    plain = analyze_style('Кот спит.')
    expressive = analyze_style('Кот спит! Почему?')
    assert plain['metrics']['punctuation_density']['question'] == 0
    assert expressive['metrics']['punctuation_density']['question'] > 0
    assert expressive['intonation']['status'] == 'unknown'


def test_government_prunes_case_but_keeps_original_candidates():
    text = 'Иван стоит в комнате.'
    rows = tokens(text)
    analyze_speech_structure(text, rows, parser=DepParser())
    rd = next(r for r in rows if r['word'] == 'комнате')['morph_readings']
    assert any('datv' in c['grammemes'] for c in rd['candidates'])
    assert any('loct' in c['grammemes'] and c['compatible'] for c in rd['candidates'])
    assert all(not c['compatible'] for c in rd['candidates'] if 'datv' in c['grammemes'])


def test_subordinate_event_is_preserved_without_world_promotion():
    text = 'Иван сказал, что Мария пришла.'
    d = analyze_speech_structure(text, tokens(text), parser=DepParser())
    arriving = next(e for e in d['event_roles'] if e['predicate'] == 'прийти')
    assert any(r['name'] == 'Мария' and r['scope'] == 'reported' for r in arriving['roles'])
    assert not any(e['predicate'] == 'прийти' for e in narrator_event_role_events(d['event_roles']))


def test_negative_and_question_events_do_not_assert_world_occurrence():
    for text in ['Иван не спал.', 'Иван пришёл?']:
        d = analyze_speech_structure(text, tokens(text), parser=DepParser())
        assert d['event_roles']
        assert not narrator_event_role_events(d['event_roles'])


def test_existing_verse_analyzer_reports_hypotheses_and_rhyme_limit():
    poem = 'Мой дядя самых честных правил,\nКогда не в шутку занемог,\nОн уважать себя заставил\nИ лучше выдумать не мог.'
    verse = analyze_style(poem)['verse']
    assert verse['status'] == 'hypothesis_from_lines'
    assert verse['rhyme_scheme'] == 'ABAB'
    assert len(verse['syllables_per_line']) == 4
    assert verse['meter']['probability'] is None
    assert verse['rhyme_lines_checked'] == 4


def test_ambiguous_source_cannot_inherit_label_level_trust():
    claims = [dict(claim_id='c', source_name='Иван', source_entity_id='иван',
        source_status='identified', source_token_range=[0, 0])]
    rows = [dict(speech_scope=dict(claim_id='c', source_entity_id='иван'),
        pronoun_readings=dict(values=['иван#1', 'иван#2']))]
    refs = [dict(referent_id=f'иван#{i}', display=f'Иван#{i}', kind='individual') for i in (1, 2)]
    annotate_source_referents(claims, rows, refs)
    attach_epistemic_evidence(claims, [], {'иван':dict(belief=.6, disbelief=.1,
        uncertainty=.3, base_rate=.2, trust=.5)})
    assert claims[0]['source_status'] == 'ambiguous'
    assert claims[0]['source_entity_id'] is None
    assert claims[0]['source_referent_ids'] == ['иван#1', 'иван#2']
    assert rows[0]['speech_scope']['source_entity_id'] is None
    assert claims[0]['epistemic']['source_trust'] is None
