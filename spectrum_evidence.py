"""Spectrum adapters for existing constraint, style and evidence mechanisms."""
from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace
from typing import Any


def crosses_clause_marker(nodes: list[Any], predicate: Any, argument: Any) -> bool:
    """Detect a dependent attached backwards across an explicit clause marker."""
    from ru_lexicon import lex
    return any((n.rel == 'mark' or ((n.lemma or n.word).lower() in lex.subordinators
                and any(v.pos in ('VERB', 'INFN', 'PRTF', 'PRTS')
                        and v.char_start is not None and n.char_end is not None
                        and v.char_start >= n.char_end for v in nodes)))
               and n.char_start is not None
               and predicate.char_start < n.char_start < argument.char_start
               for n in nodes)


@lru_cache(maxsize=4096)
def _analyses(word: str) -> tuple:
    from engine.language.morph_transducer import MorphTransducer, MorphParse
    from engine.language.inflector import _cached_reverse_lookup, _build_analysis, _grammemes_from_str
    transducer = MorphTransducer()
    candidates = list(transducer.analyze(word))
    # analyze() groups homonymous case rows by lemma/POS. Expand the actual
    # frozen paradigm rows so unification sees datv/loct/etc independently.
    for lemma, pos, gram_str, _form in _cached_reverse_lookup(word.lower()):
        analysis = _build_analysis(lemma, pos, gram_str, _grammemes_from_str(gram_str), score=0)
        parse = transducer._analysis_to_parse(analysis)
        if not any((p.lemma, p.pos, p.grammemes) == (parse.lemma, parse.pos, parse.grammemes)
                   for p in candidates):
            candidates.append(parse)
    return tuple(candidates) or (MorphParse(lemma=word.lower(), pos='UNKN', source='unknown'),)


def annotate_unification(nodes: list[Any], offset: int, tokens: list[dict],
                         token_range_for_chars: Any, starts: list[int]) -> dict:
    """Expose arc consistency under parser constraints without discarding readings.

    Raw domains and conditional compatible domains stay separate. AC-3 does not
    prove a joint assignment exists; parse ranking is not a probability.
    """
    from engine.language.feature_unification import ConstraintGraph, Constraint
    content = [n for n in nodes if n.pos not in ('PUNCT', 'DASH')]
    analyses = [list(_analyses(n.word)) for n in content]
    safe_nodes = []
    by_idx = {n.idx: n for n in nodes}
    for n in nodes:
        head = by_idx.get(n.head)
        invalid = head is not None and n.char_start is not None and head.char_start is not None and crosses_clause_marker(nodes, head, n)
        safe_nodes.append(SimpleNamespace(idx=n.idx, word=n.word, pos=n.pos,
            head=-1 if invalid else n.head, rel=n.rel, feats=getattr(n, 'feats', {})))
    graph = ConstraintGraph.from_dep_tree(safe_nodes, analyses)
    # The existing AC-3 seed queues government only governor->dependent.
    # An equivalent unary target constraint enforces the governed case on the
    # dependent too, using the same solver and compatibility predicate.
    for c in list(graph.constraints):
        if c.kind == 'government':
            graph.constraints.append(Constraint(c.target, c.target, c.kind,
                c.dimensions, c.assigned_values, c.label + ' governed-case'))
    result = graph.solve()
    for position, node in enumerate(content):
        if node.char_start is None or node.char_end is None:
            continue
        span = token_range_for_chars(tokens, starts, offset + node.char_start, offset + node.char_end)
        if not span:
            continue
        # ConstraintGraph has no public domain export; these are its actual
        # AC-3 survivor domains, not a reconstruction from the ranked winner.
        survivors = graph._domains[position] if result.success else None
        candidates = []
        for p in analyses[position]:
            candidates.append({'lemma': p.lemma, 'pos': p.pos,
                'grammemes': sorted(p.grammemes), 'source': p.source,
                'compatible': p in survivors if survivors is not None else None,
                'probability': None})
        tokens[span[0]]['morph_readings'] = {
            'status': 'arc_consistent' if result.success else 'constraint_conflict',
            'candidates': candidates,
            'constraints': [c.label for c in graph.constraints
                            if position in (c.source, c.target)],
            'source': 'feature_unification.ConstraintGraph',
        }
    return {'status': 'arc_consistent' if result.success else 'constraint_conflict',
            'constraints_applied': result.constraints_applied,
            'pruned_count': result.pruned_count,
            'remaining_ambiguity': result.remaining_ambiguity}


def annotate_source_referents(claims: list[dict], tokens: list[dict], referents: list[dict]) -> None:
    """A repeated label identifies a set of bearers, not one trusted person."""
    by_id = {ref['referent_id']: ref for ref in referents}
    for claim in claims:
        span = claim.get('source_token_range')
        row = tokens[span[0]] if span else {}
        reading = row.get('pronoun_readings', {})
        candidates = [rid for rid in reading.get('values', []) if rid in by_id]
        label = (claim.get('source_entity_id') or claim.get('source_name') or '').lower().replace('ё', 'е')
        if not candidates:
            candidates = [rid for rid, ref in by_id.items()
                if ref['kind'] == 'individual' and rid.rsplit('#', 1)[0] == label]
        if len(candidates) > 1:
            claim.update(source_status='ambiguous', source_entity_id=None,
                source_referent_ids=candidates,
                source_candidates=[by_id[rid]['display'] for rid in candidates])
    by_claim = {claim['claim_id']: claim for claim in claims}
    fields = ('source_name', 'source_entity_id', 'source_status', 'source_referent_ids', 'source_candidates')
    for row in tokens:
        scopes = list(row.get('speech_scopes', []))
        if row.get('speech_scope'):
            scopes.append(row['speech_scope'])
        for scope in scopes:
            claim = by_claim.get(scope['claim_id'])
            if claim:
                scope.update({key: claim.get(key) for key in fields})


def attach_epistemic_evidence(claims: list[dict], events: list[dict],
                              source_assessments: dict | None = None) -> None:
    """Track syntactic hypotheses; never publish the tracker's default prior."""
    from engine.epistemic.evidence_tracker import EvidenceTracker
    tracker = EvidenceTracker()
    for claim in claims:
        record = tracker.register_claim(claim['claim_id'],
            f"Content attributed to {claim.get('source_name') or 'unknown source'}",
            reason='speech attribution does not establish world truth')
        claim['epistemic'] = {'truth_kind': record.truth_kind.value,
            'transitions': record.transitions, 'source_trust': None,
            'probability': None, 'source': 'EvidenceTracker.register_claim'}
        if claim.get('source_status') == 'ambiguous':
            claim['epistemic']['assessment_status'] = 'source_identity_unresolved'
        assessment = (source_assessments or {}).get(claim.get('source_entity_id'))
        if assessment is not None:
            from engine.epistemic.opinion import Opinion
            opinion = Opinion(assessment['belief'], assessment['disbelief'],
                              assessment['uncertainty'], assessment['base_rate'])
            discounted = opinion.discount(assessment['trust'])
            claim['epistemic'].update(source_trust=assessment['trust'],
                support={'belief': discounted.b, 'disbelief': discounted.d,
                         'uncertainty': discounted.u},
                assessment_source='request.source_assessments',
                discount_source='Opinion.discount')
    for event in events:
        for role in event['roles']:
            key = f"{event['event_id']}:{role['token_range']}:{role['role']}"
            record = tracker.register_claim(key, f"{role['name']} {role['role']} {event['predicate']}",
                reason='dependency role hypothesis')
            if role.get('clause_boundary_conflict'):
                tracker.refute(key, 'dependency attachment crosses an explicit subordinate marker')
            role['epistemic'] = {'truth_kind': record.truth_kind.value,
                'transitions': record.transitions, 'probability': None,
                'source': 'EvidenceTracker'}


@lru_cache(maxsize=1)
def _style_analyzer() -> Any:
    # rus_lang.__init__ imports its interpreter and MorphIR/MLX. The existing
    # style module itself is pure Python; load exactly that module independently.
    import importlib.util
    import sys
    from pathlib import Path
    import engine
    path = Path(engine.__file__).parent / 'codetools/rus_lang/style_analyser.py'
    spec = importlib.util.spec_from_file_location('_spectrum_style_analyser', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.StyleAnalyser()


def analyze_style(text: str) -> dict:
    from engine.reasoning.text_structure import analyze_poem
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    form = analyze_poem(text) if len(lines) > 1 else None
    return {'status': 'observed', 'source': 'StyleAnalyser.analyse',
            'metrics': _style_analyzer().analyse(text),
            'intonation': {'status': 'unknown', 'reason': 'audio_required',
                           'source': 'engine.dialogue.prosody_analyzer.analyze_prosody'},
            'verse': {'status': 'hypothesis_from_lines' if form else 'not_applicable',
                'source': 'engine.reasoning.text_structure.analyze_poem',
                'syllables_per_line': form.syllables_per_line if form else [],
                'burstiness': form.burstiness if form else None,
                'meter': {'name': form.meter.name_ru, 'pattern': form.meter.pattern,
                          'match_score': form.meter.confidence, 'probability': None}
                          if form and form.meter else None,
                'rhyme_scheme': form.rhyme_scheme if form else None,
                'rhyme_lines_checked': min(8, len(lines)) if form else 0,
                'total_lines': len(lines),
                'limitations': ['stress_estimated_not_observed', 'rhyme_by_written_endings']},
            'harmony': {'status': 'not_computed', 'reason': 'no_verified_text_analyzer'}}


def annotate_event_context(events: list[dict], tokens: list[dict], text: str) -> None:
    """Show observed anchors and explicit causal markers with source scope.

    A causal marker is textual evidence for a stated relation, not evidence
    that the alleged cause is true. Unrecognized causes remain unknown.
    """
    from ru_lexicon import lex
    from engine.language.narrative_lexicon import get_narrative_lexicon
    from engine.ingestion._i18n import load_ingestion_strings
    temporal_markers = set(get_narrative_lexicon('ru').temporal_markers) | set(
        load_ingestion_strings().get('deictic_time_adverbs', []))
    for event in events:
        pivot = event['predicate_token_range'][0]
        left = pivot
        while left > 0 and tokens[left-1]['word'] not in '.!?…' and '\n' not in tokens[left].get('_gap', ''):
            left -= 1
        right = pivot
        while right + 1 < len(tokens) and tokens[right]['word'] not in '.!?…' and '\n' not in tokens[right+1].get('_gap', ''):
            right += 1
        source = tokens[pivot].get('speech_scope')
        event['source_name'] = source.get('source_name') if source else 'рассказчик'
        event['source_claim_id'] = source.get('claim_id') if source else None
        event.update({key: source.get(key) if source else None for key in
            ('source_status', 'source_referent_ids', 'source_candidates')})
        event['time'] = [{'text': t['word'], 'token_range': [i, i],
                         'source': 'temporal_lexicon', 'status': 'textual_anchor'}
                        for i, t in enumerate(tokens[left:right+1], left)
                        if (t.get('lemma') or t['word'].lower()) in temporal_markers
                        and t.get('speech_scope', {}).get('claim_id') == event['source_claim_id']]
        event['cause'] = {'status': 'unknown', 'source_name': event['source_name'],
                          'source_claim_id': event['source_claim_id']}
        markers = [i for i in range(left, right+1)
                   if (tokens[i].get('discourse_role') == 'cause'
                       or lex.discourse_roles.get(tokens[i].get('lemma')) == 'cause'
                       or tokens[i].get('sem_role') == 'cause')]
        # Only a marker following this event can introduce its reason. A causal
        # clause's own event must not inherit the cause of the preceding event.
        following = [i for i in markers if i > pivot]
        if following:
            start = following[0]
            end = right
            if any(tokens[i].get('speech_scope', {}).get('claim_id') != event['source_claim_id']
                   for i in range(start, end+1)):
                continue
            char_span = [tokens[start]['char_start'], tokens[end]['char_end']]
            event['cause'].update(status='explicit', token_range=[start, end],
                char_range=char_span, text=text[char_span[0]:char_span[1]],
                source='discourse_role:cause', world_status='not_assessed')
