"""Speech-scope and dependency-role evidence for Logos Spectrum.

This adapter keeps quoted and reported content separate from narrator-scoped
event roles. It uses the repository's narrative lexicon and dependency parser;
it does not import the optional MLX role learner or MorphIR.
"""
from __future__ import annotations

from bisect import bisect_left
import re
from typing import Any
from spectrum_evidence import crosses_clause_marker, annotate_unification, attach_epistemic_evidence


_QUOTED_TEXT_RE = re.compile(r'«[^»]*»|“[^”]*”|„[^“]*“|"[^"]*"')
_QUOTE_SEPARATORS = frozenset(" \t\r\n,.:;—–-")
_QUOTE_PAIRS = {"«": "»", "“": "”", "„": "“", '"': '"'}
_ROLE_BY_RELATION = {
    "nsubj": "agent",
    "nsubj:pass": "patient",
    "obj": "patient",
    "iobj": "recipient",
    "obl:agent": "agent",
    "obl:loc": "location",
    "obl:inst": "instrument",
}
_SUBJECT_RELATIONS = {"nsubj", "nsubj:pass"}
_PREDICATE_POS = {"VERB", "INFN", "PRTF", "PRTS"}


def _sentence_spans(text: str):
    start = 0
    quote_stack = []
    index = 0
    while index < len(text):
        char = text[index]
        if quote_stack and char == quote_stack[-1]:
            quote_stack.pop()
        elif char in _QUOTE_PAIRS:
            quote_stack.append(_QUOTE_PAIRS[char])

        if not quote_stack and char in ".!?…":
            end = index + 1
            while end < len(text) and text[end] in ".!?…":
                end += 1
            raw = text[start:end]
            stripped = raw.strip()
            if stripped:
                leading = len(raw) - len(raw.lstrip())
                yield start + leading, start + leading + len(stripped)
            start = end
            index = end
            continue
        if not quote_stack and char == "\n":
            raw = text[start:index]
            stripped = raw.strip()
            if stripped:
                leading = len(raw) - len(raw.lstrip())
                yield start + leading, start + leading + len(stripped)
            start = index + 1
        index += 1

    raw = text[start:]
    stripped = raw.strip()
    if stripped:
        leading = len(raw) - len(raw.lstrip())
        yield start + leading, start + leading + len(stripped)


def _token_range_for_chars(tokens: list[dict], starts: list[int], start: int,
                           end: int) -> list[int] | None:
    if not tokens or end <= start:
        return None
    first = bisect_left(starts, start)
    if first > 0 and int(tokens[first - 1].get("char_end", -1)) > start:
        first -= 1
    while first < len(tokens) and int(tokens[first].get("char_end", -1)) <= start:
        first += 1
    last = bisect_left(starts, end) - 1
    while last >= first and int(tokens[last].get("char_start", -1)) >= end:
        last -= 1
    if first >= len(tokens) or last < first:
        return None
    return [first, last]


def _token_range_char_span(tokens: list[dict], token_range: list[int] | None):
    if not token_range:
        return None
    start, end = token_range
    if start < 0 or end >= len(tokens) or end < start:
        return None
    first, last = tokens[start], tokens[end]
    if "char_start" not in first or "char_end" not in last:
        return None
    return [int(first["char_start"]), int(last["char_end"])]


def _load_lexicons():
    from engine.language.language_config import load_sub_conjunctions
    from engine.language.narrative_lexicon import get_narrative_lexicon

    return (
        frozenset(value.lower() for value in get_narrative_lexicon("ru").speech_verbs),
        frozenset(value.lower() for value in load_sub_conjunctions("ru")),
    )


def _claim_scope(claim: dict) -> dict:
    return {
        "claim_id": claim["claim_id"],
        "mode": claim["mode"],
        "claim_status": claim["claim_status"],
        "world_status": claim["world_status"],
        "source_name": claim.get("source_name"),
        "source_entity_id": claim.get("source_entity_id"),
        "parent_claim_id": claim.get("parent_claim_id"),
    }


def annotate_token_scopes(tokens: list[dict], claims: list[dict]) -> None:
    """Attach all containing claim scopes to tokens; the innermost is primary."""
    starts: dict[int, list[dict]] = {}
    ends: dict[int, list[str]] = {}
    for claim in claims:
        span = claim.get("content_token_range")
        if not span or span[0] < 0 or span[1] >= len(tokens) or span[1] < span[0]:
            continue
        starts.setdefault(span[0], []).append(claim)
        ends.setdefault(span[1] + 1, []).append(claim["claim_id"])
    active: dict[str, dict] = {}
    for token_index, token in enumerate(tokens):
        for claim_id in ends.get(token_index, []):
            active.pop(claim_id, None)
        for claim in starts.get(token_index, []):
            active[claim["claim_id"]] = claim
        scopes = sorted(
            active.values(),
            key=lambda claim: (
                claim["content_token_range"][1] - claim["content_token_range"][0],
                claim["content_token_range"][0],
            ),
            reverse=True,
        )
        if scopes:
            token["speech_scopes"] = [_claim_scope(claim) for claim in scopes]
            token["speech_scope"] = _claim_scope(scopes[-1])
        else:
            token.pop("speech_scopes", None)
            token.pop("speech_scope", None)


def annotate_event_role_scopes(event_roles: list[dict], tokens: list[dict]) -> None:
    """Bind each event-role record to its token's claim scope, if any."""
    for token in tokens:
        token.pop("event_roles", None)
    for event in event_roles:
        scopes_in_event = []
        for role in event.get("roles", []):
            token_range = role.get("token_range") or []
            token_index = token_range[0] if token_range else -1
            token = tokens[token_index] if 0 <= token_index < len(tokens) else {}
            scopes = token.get("speech_scopes", [])
            role["source_claim_ids"] = [scope["claim_id"] for scope in scopes]
            role["source_claim_id"] = scopes[-1]["claim_id"] if scopes else None
            role["scope"] = scopes[-1]["mode"] if scopes else ("unresolved_clause" if role.get("clause_boundary_conflict") else "narrator")
            role["world_status"] = scopes[-1]["world_status"] if scopes else ("not_assessed" if role.get("clause_boundary_conflict") else "narrator_asserted")
            if not scopes and event.get('polarity') == 'negated':
                role['world_status'] = 'narrator_negated'
            if not scopes and event.get('assertion_status') == 'question':
                role['world_status'] = 'not_asserted_question'
            role["event_id"] = event.get("event_id")
            if 0 <= token_index < len(tokens):
                tokens[token_index].setdefault("event_roles", []).append(role)
            if role["scope"] not in scopes_in_event:
                scopes_in_event.append(role["scope"])
        event["scope"] = scopes_in_event[0] if len(scopes_in_event) == 1 else (
            "mixed" if scopes_in_event else "narrator"
        )
        event["world_status"] = (
            "narrator_negated" if event.get('polarity') == 'negated' else
            "not_asserted_question" if event.get('assertion_status') == 'question' else
            "narrator_asserted" if event["scope"] == "narrator" else "not_assessed"
        )


def narrator_event_role_events(event_roles: list[dict]) -> list[dict]:
    """Return only narrator-scoped role rows for the world knowledge graph."""
    filtered = []
    for event in event_roles:
        if event.get('polarity') == 'negated' or event.get('assertion_status') == 'question':
            continue
        roles = [role for role in event.get("roles", [])
                 if role.get("scope", "narrator") == "narrator"]
        if roles:
            filtered.append({**event, "roles": roles})
    return filtered


def _source_for_reporter(nodes: list[Any], reporter: Any, content_start: int,
                         content_end: int, source_offset: int,
                         tokens: list[dict], token_starts: list[int]):
    candidates = [
        node for node in nodes
        if node.head == reporter.idx
        and node.rel in _SUBJECT_RELATIONS
        and node.char_start is not None
        and node.char_end is not None
        and not (content_start <= node.char_start < content_end)
    ]
    if not candidates:
        return None, None, None, "source_unresolved"
    subject = min(candidates, key=lambda node: abs(node.char_start - reporter.char_start))
    global_start = source_offset + int(subject.char_start)
    global_end = source_offset + int(subject.char_end)
    token_range = _token_range_for_chars(tokens, token_starts, global_start, global_end)
    if not token_range:
        return None, None, None, "source_unresolved"
    token_index = token_range[0]
    token = tokens[token_index]
    entity_id = token.get("entity_id")
    source_name = token.get("pronoun_ref") or token.get("clean") or token.get("word")
    status = "identified" if entity_id or token.get("pronoun_ref") else "surface_only"
    return source_name, entity_id, token_range, status


def _quoted_speech_claims_for_sentence(
    sentence: str,
    source_offset: int,
    nodes: list[Any],
    tokens: list[dict],
    token_starts: list[int],
    speech_verbs: frozenset[str],
    existing_claims: list[dict],
) -> list[tuple[dict, tuple[int, int]]]:
    """Attribute a quoted span only when a nearby speech tag identifies it."""
    reporters = [
        node for node in nodes
        if node.lemma.lower() in speech_verbs
        and node.pos in {"VERB", "INFN"}
        and node.char_start is not None and node.char_end is not None
    ]
    if not reporters:
        return []

    attributed = []
    for match in _QUOTED_TEXT_RE.finditer(sentence):
        quote_start, quote_end = match.span()
        body_start, body_end = quote_start + 1, quote_end - 1
        if not sentence[body_start:body_end].strip():
            continue
        global_body_start = source_offset + body_start
        global_body_end = source_offset + body_end
        if any(
            claim.get("mode") == "direct"
            and claim.get("content_char_range")
            and claim["content_char_range"][0] <= global_body_start
            and global_body_end <= claim["content_char_range"][1]
            for claim in existing_claims
        ):
            continue

        candidates = []
        for reporter in reporters:
            if reporter.char_end <= quote_start:
                gap = sentence[reporter.char_end:quote_start]
                distance = quote_start - reporter.char_end
            elif reporter.char_start >= quote_end:
                gap = sentence[quote_end:reporter.char_start]
                distance = reporter.char_start - quote_end
            else:
                continue
            if any(char not in _QUOTE_SEPARATORS for char in gap):
                continue
            candidates.append((distance, reporter))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0])
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            continue
        reporter = candidates[0][1]
        quote_token_range = _token_range_for_chars(
            tokens, token_starts,
            source_offset + quote_start,
            source_offset + quote_end,
        )
        reporter_token_range = _token_range_for_chars(
            tokens, token_starts,
            source_offset + int(reporter.char_start),
            source_offset + int(reporter.char_end),
        )
        if not quote_token_range or not reporter_token_range:
            continue
        source_name, source_entity_id, source_token_range, source_status = _source_for_reporter(
            nodes, reporter, quote_start, quote_end,
            source_offset, tokens, token_starts,
        )
        claim_id = f"direct-quoted-{quote_token_range[0]}-{quote_token_range[1]}"
        claim = {
            "claim_id": claim_id,
            "mode": "direct",
            "source_name": source_name,
            "source_entity_id": source_entity_id,
            "source_token_range": source_token_range,
            "source_status": source_status,
            "reporting_predicate": reporter.lemma,
            "reporting_predicate_token_range": reporter_token_range,
            "content_token_range": quote_token_range,
            "content_char_range": [source_offset + quote_start, source_offset + quote_end],
            "polarity": "attributed_utterance",
            "claim_status": "attributed" if source_name else "speaker_unresolved",
            "world_status": "not_assessed",
            "parent_claim_id": None,
            "evidence": [
                {"type": "quoted_utterance", "token_range": quote_token_range},
                {"type": "narrative_speech_lexicon", "token_range": reporter_token_range},
                *([{"type": "speaker_dependency", "token_range": source_token_range}]
                  if source_token_range else []),
            ],
        }
        attributed.append((claim, (global_body_start, global_body_end)))
    return attributed


def _reported_claims_for_sentence(
    sentence: str,
    source_offset: int,
    nodes: list[Any],
    tokens: list[dict],
    token_starts: list[int],
    speech_verbs: frozenset[str],
    sub_conjunctions: frozenset[str],
) -> list[dict]:
    reporters = sorted(
        [node for node in nodes
         if node.lemma.lower() in speech_verbs
         and node.pos in {"VERB", "INFN"}
         and node.char_start is not None and node.char_end is not None],
        key=lambda node: node.char_start,
    )
    if not reporters:
        return []
    claims = []
    for reporter_index, reporter in enumerate(reporters):
        next_reporter_start = (
            reporters[reporter_index + 1].char_start
            if reporter_index + 1 < len(reporters) else len(sentence)
        )
        markers = [
            node for node in nodes
            if node.lemma.lower() in sub_conjunctions
            and node.char_start is not None and node.char_end is not None
            and reporter.char_end <= node.char_start < next_reporter_start
        ]
        if not markers:
            continue
        marker = min(markers, key=lambda node: node.char_start)
        has_predicate = any(
            node.pos in _PREDICATE_POS
            and node.char_start is not None
            and node.char_start >= marker.char_end
            and node.idx != reporter.idx
            for node in nodes
        )
        if not has_predicate:
            continue
        content_start = source_offset + int(marker.char_start)
        content_end = source_offset + len(sentence)
        content_token_range = _token_range_for_chars(
            tokens, token_starts, content_start, content_end
        )
        if not content_token_range:
            continue
        reporter_range = _token_range_for_chars(
            tokens,
            token_starts,
            source_offset + int(reporter.char_start),
            source_offset + int(reporter.char_end),
        )
        if not reporter_range:
            continue
        marker_range = _token_range_for_chars(
            tokens,
            token_starts,
            source_offset + int(marker.char_start),
            source_offset + int(marker.char_end),
        )
        if not marker_range:
            continue
        source_name, source_entity_id, source_token_range, source_status = _source_for_reporter(
            nodes, reporter, int(marker.char_start), len(sentence),
            source_offset, tokens, token_starts,
        )
        negation_nodes = [
            node for node in nodes
            if node.head == reporter.idx and node.rel == "advmod:neg"
        ]
        negated = bool(negation_nodes)
        claim_id = f"reported-{reporter_range[0]}-{marker_range[0]}"
        claim_status = "not_asserted" if negated else "syntactic_candidate"
        claims.append({
            "claim_id": claim_id,
            "mode": "reported",
            "source_name": source_name,
            "source_entity_id": source_entity_id,
            "source_token_range": source_token_range,
            "source_status": source_status,
            "reporting_predicate": reporter.lemma,
            "reporting_predicate_token_range": reporter_range,
            "content_token_range": content_token_range,
            "content_char_range": [content_start, content_end],
            "polarity": "negated_report" if negated else "reported",
            "claim_status": claim_status,
            "world_status": "not_asserted" if negated else "not_assessed",
            "parent_claim_id": None,
            "evidence": [
                {"type": "narrative_speech_lexicon", "token_range": reporter_range},
                {"type": "subordinate_clause_marker", "token_range": marker_range},
                *([{"type": "dependency_negation", "token_range": [
                    _token_range_for_chars(
                        tokens, token_starts,
                        source_offset + int(node.char_start),
                        source_offset + int(node.char_end),
                    )[0],
                    _token_range_for_chars(
                        tokens, token_starts,
                        source_offset + int(node.char_start),
                        source_offset + int(node.char_end),
                    )[1],
                ]} for node in negation_nodes
                  if node.char_start is not None and node.char_end is not None
                  and _token_range_for_chars(
                      tokens, token_starts,
                      source_offset + int(node.char_start),
                      source_offset + int(node.char_end),
                  )]),
            ],
        })
    return claims


def _dependency_event_roles(
    nodes: list[Any], source_offset: int, tokens: list[dict], token_starts: list[int]
) -> list[dict]:
    events = []
    for predicate in nodes:
        if predicate.pos not in _PREDICATE_POS or predicate.char_start is None or predicate.char_end is None:
            continue
        predicate_range = _token_range_for_chars(
            tokens, token_starts,
            source_offset + int(predicate.char_start),
            source_offset + int(predicate.char_end),
        )
        if not predicate_range:
            continue
        role_rows = []
        for argument in nodes:
            role_name = _ROLE_BY_RELATION.get(argument.rel)
            if argument.rel == 'obl' and getattr(argument, 'case', None) == 'loct':
                role_name = 'location'
            if argument.head != predicate.idx or not role_name:
                continue
            if argument.pos not in {"NOUN", "NPRO", "PROPN"}:
                continue
            if argument.char_start is None or argument.char_end is None:
                continue
            global_start = source_offset + int(argument.char_start)
            global_end = source_offset + int(argument.char_end)
            token_range = _token_range_for_chars(tokens, token_starts, global_start, global_end)
            if not token_range:
                continue
            token = tokens[token_range[0]]
            name = token.get("clean") or token.get("word") or argument.word
            lemma = (token.get("lemma") or argument.lemma or argument.word).lower().replace("ё", "е")
            entity_id = token.get("entity_id") or f"role:{lemma}"
            role_rows.append({
                "entity_id": entity_id,
                "name": name,
                "role": role_name,
                "token_range": token_range,
                "char_range": [global_start, global_end],
                "case": getattr(argument, "case", None),
                "clause_boundary_conflict": crosses_clause_marker(nodes, predicate, argument),
                "confidence": 0.65,
                "source": "dependency_parse",
                "dependency_relation": argument.rel,
                "evidence_grade": "syntactic",
            })
        if role_rows:
            role_indices = [index for role in role_rows for index in role["token_range"]]
            span = [min([predicate_range[0], *role_indices]),
                    max([predicate_range[1], *role_indices])]
            char_starts = [source_offset + int(predicate.char_start)] + [
                role["char_range"][0] for role in role_rows
            ]
            char_ends = [source_offset + int(predicate.char_end)] + [
                role["char_range"][1] for role in role_rows
            ]
            events.append({
                "event_id": f"event-{predicate_range[0]}",
                "predicate": predicate.lemma or predicate.word,
                "polarity": 'negated' if any(n.head == predicate.idx and n.rel == 'advmod:neg' for n in nodes) else 'positive',
                "assertion_status": 'question' if any(n.word == '?' for n in nodes) else 'syntactic_candidate',
                "predicate_token_range": predicate_range,
                "token_range": span,
                "char_range": [min(char_starts), max(char_ends)],
                "roles": role_rows,
                "incomplete_event": False,
                "missing_roles": [],
            })
    return events


def analyze_speech_structure(
    text: str,
    tokens: list[dict],
    dialogue_turns: list[dict] | None = None,
    *,
    parser: Any | None = None,
    speech_verbs: frozenset[str] | None = None,
    sub_conjunctions: frozenset[str] | None = None,
) -> dict:
    """Return direct/reported claim spans, dependency roles, and diagnostics.

    Reported clauses remain syntactic candidates unless a reporting predicate
    is present. A negative reporting predicate marks its complement
    ``not_asserted``. Direct dialogue uses the existing speaker/turn evidence.
    """
    dialogue_turns = dialogue_turns or []
    token_starts = [int(token.get("char_start", -1)) for token in tokens]
    claims = []
    diagnostics = []
    for turn in dialogue_turns:
        start = turn.get("start_token")
        end = turn.get("end_token")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end >= len(tokens) or end < start:
            continue
        token_range = [start, end]
        speaker = turn.get("speaker")
        confidence = turn.get("confidence")
        claims.append({
            "claim_id": f"direct-{turn.get('turn_id', start)}",
            "mode": "direct",
            "source_name": speaker,
            "source_entity_id": turn.get("entity_id"),
            "source_token_range": None,
            "source_status": "identified" if turn.get("entity_id") else (
                "surface_only" if speaker else "source_unresolved"
            ),
            "content_token_range": token_range,
            "content_char_range": _token_range_char_span(tokens, token_range),
            "polarity": "attributed_utterance",
            "claim_status": "attributed" if speaker else "speaker_unresolved",
            "world_status": "not_assessed",
            "confidence": confidence,
            "turn_id": turn.get("turn_id"),
            "parent_claim_id": None,
            "evidence": [{
                "type": "dialogue_turn",
                "token_range": token_range,
                "confidence": confidence,
            }],
        })

    if not tokens:
        return {"speech_claims": claims, "event_roles": [], "diagnostics": diagnostics, "morph_unification": []}
    if any("char_start" not in token or "char_end" not in token for token in tokens):
        diagnostics.append({"code": "source_spans_unavailable", "stage": "speech_structure"})
        return {"speech_claims": claims, "event_roles": [], "diagnostics": diagnostics, "morph_unification": []}

    if speech_verbs is None or sub_conjunctions is None:
        try:
            loaded_speech_verbs, loaded_sub_conjunctions = _load_lexicons()
            speech_verbs = speech_verbs if speech_verbs is not None else loaded_speech_verbs
            sub_conjunctions = sub_conjunctions if sub_conjunctions is not None else loaded_sub_conjunctions
        except Exception as exc:
            diagnostics.append({
                "code": "narrative_lexicon_unavailable",
                "stage": "speech_attribution",
                "error": f"{type(exc).__name__}: {exc}",
            })
            speech_verbs = speech_verbs or frozenset()
            sub_conjunctions = sub_conjunctions or frozenset()
    speech_verbs = frozenset(value.lower() for value in speech_verbs)
    sub_conjunctions = frozenset(value.lower() for value in sub_conjunctions)

    needs_parser = any(
        token.get("pos") in _PREDICATE_POS
        or (token.get("lemma") or token.get("word", "")).lower() in speech_verbs
        for token in tokens
    )
    if needs_parser and parser is None:
        try:
            from engine.parsing.dep_parser import DepParser
            parser = DepParser()
        except Exception as exc:
            diagnostics.append({
                "code": "dependency_parser_unavailable",
                "stage": "speech_structure",
                "error": f"{type(exc).__name__}: {exc}",
            })

    event_roles = []
    morph_unification = []
    if parser is not None:
        for sentence_start, sentence_end in _sentence_spans(text):
            sentence_token_range = _token_range_for_chars(
                tokens, token_starts, sentence_start, sentence_end
            )
            if not sentence_token_range:
                continue
            sentence = text[sentence_start:sentence_end]
            sentence_rows = tokens[sentence_token_range[0]:sentence_token_range[1] + 1]
            has_verb = any(
                row.get("pos") in _PREDICATE_POS
                or (row.get("lemma") or row.get("word", "")).lower() in speech_verbs
                for row in sentence_rows
            )
            if not has_verb:
                continue
            try:
                nodes = parser.parse_tree(sentence)
            except Exception as exc:
                diagnostics.append({
                    "code": "dependency_parse_failed",
                    "stage": "speech_structure",
                    "char_range": [sentence_start, sentence_end],
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            try:
                unified = annotate_unification(nodes, sentence_start, tokens,
                    _token_range_for_chars, token_starts)
                morph_unification.append({**unified, 'char_range': [sentence_start, sentence_end]})
            except Exception as exc:
                diagnostics.append({'code': 'unification_failed',
                    'char_range': [sentence_start, sentence_end],
                    'error': f'{type(exc).__name__}: {exc}'})
            quoted_rows = _quoted_speech_claims_for_sentence(
                sentence, sentence_start, nodes, tokens, token_starts,
                speech_verbs, claims,
            )
            claims.extend(claim for claim, _ in quoted_rows)

            quote_body_token_ranges = [
                token_range for _, body_range in quoted_rows
                if (token_range := _token_range_for_chars(
                    tokens, token_starts, body_range[0], body_range[1]
                ))
            ]
            sentence_events = _dependency_event_roles(
                nodes, sentence_start, tokens, token_starts
            )
            event_roles.extend(
                event for event in sentence_events
                if not any(
                    event.get("predicate_token_range", [1, 0])[0] <= quote_range[1]
                    and quote_range[0] <= event.get("predicate_token_range", [1, 0])[1]
                    for quote_range in quote_body_token_ranges
                )
            )
            # Keep rejected parent attachments as evidence, and recover the
            # subordinate event through the same existing parser on its body.
            boundary_markers = [n for n in nodes if n.char_start is not None
                and n.char_end is not None and (n.lemma or n.word).lower() in sub_conjunctions
                and any(crosses_clause_marker(nodes, pred, arg)
                    for pred in nodes if pred.pos in _PREDICATE_POS and pred.char_start is not None
                    for arg in nodes if arg.head == pred.idx and arg.char_start is not None
                    and n.char_start < arg.char_start)]
            for marker in boundary_markers:
                raw_body = sentence[int(marker.char_end):]
                body = raw_body.lstrip()
                try:
                    body_nodes = parser.parse_tree(body)
                    if any(n.char_start is None or n.char_end is None
                           or body[n.char_start:n.char_end].casefold() != n.word.casefold()
                           for n in body_nodes):
                        continue
                    body_offset = sentence_start + int(marker.char_end) + len(raw_body) - len(body)
                    body_events = _dependency_event_roles(body_nodes, body_offset, tokens, token_starts)
                    existing_ids = {e['event_id'] for e in event_roles}
                    event_roles.extend(e for e in body_events if e['event_id'] not in existing_ids)
                    unified = annotate_unification(body_nodes, body_offset, tokens,
                        _token_range_for_chars, token_starts)
                    morph_unification.append({**unified, 'char_range': [body_offset, sentence_end]})
                except Exception as exc:
                    diagnostics.append({'code': 'subordinate_parse_failed',
                        'error': f'{type(exc).__name__}: {exc}'})
            for _, (body_start, body_end) in quoted_rows:
                body = text[body_start:body_end]
                if not body.strip():
                    continue
                body_token_range = _token_range_for_chars(
                    tokens, token_starts, body_start, body_end
                )
                body_rows = tokens[body_token_range[0]:body_token_range[1] + 1] if body_token_range else []
                has_body_verb = any(
                    row.get("pos") in _PREDICATE_POS
                    or (row.get("lemma") or row.get("word", "")).lower() in speech_verbs
                    for row in body_rows
                )
                if not has_body_verb:
                    continue
                try:
                    body_nodes = parser.parse_tree(body)
                except Exception as exc:
                    diagnostics.append({
                        "code": "quoted_dependency_parse_failed",
                        "stage": "speech_structure",
                        "char_range": [body_start, body_end],
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                event_roles.extend(_dependency_event_roles(
                    body_nodes, body_start, tokens, token_starts
                ))
                claims.extend(_reported_claims_for_sentence(
                    body, body_start, body_nodes, tokens, token_starts,
                    speech_verbs, sub_conjunctions,
                ))
            overlaps_direct_turn = any(
                sentence_start < span[1] and span[0] < sentence_end
                for span in [
                    claim["content_char_range"] for claim in claims
                    if claim["mode"] == "direct" and claim.get("content_char_range")
                ]
            )
            if not overlaps_direct_turn:
                claims.extend(_reported_claims_for_sentence(
                    sentence, sentence_start, nodes, tokens, token_starts,
                    speech_verbs, sub_conjunctions,
                ))

    # Link nested report claims to the smallest enclosing claim that contains
    # their reporting predicate. This is an interval relation, not a truth claim.
    for claim in claims:
        if claim["mode"] != "reported":
            continue
        reporter_span = claim.get("reporting_predicate_token_range") or []
        if not reporter_span:
            continue
        enclosing = [
            other for other in claims
            if other is not claim
            and other.get("content_token_range")
            and other["content_token_range"][0] <= reporter_span[0]
            and reporter_span[1] <= other["content_token_range"][1]
        ]
        if enclosing:
            parent = min(
                enclosing,
                key=lambda other: other["content_token_range"][1]
                                  - other["content_token_range"][0],
            )
            claim["parent_claim_id"] = parent["claim_id"]

    annotate_token_scopes(tokens, claims)
    annotate_event_role_scopes(event_roles, tokens)
    attach_epistemic_evidence(claims, event_roles)
    return {
        "speech_claims": claims,
        "event_roles": event_roles,
        "diagnostics": diagnostics,
        "morph_unification": morph_unification,
    }


__all__ = [
    "analyze_speech_structure",
    "annotate_event_role_scopes",
    "annotate_token_scopes",
    "narrator_event_role_events",
]
