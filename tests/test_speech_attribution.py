import re
import unittest

from speech_attribution import analyze_speech_structure, narrator_event_role_events


class FakeNode:
    def __init__(self, idx, word, lemma, pos, head, rel, start, end):
        self.idx = idx
        self.word = word
        self.lemma = lemma
        self.pos = pos
        self.head = head
        self.rel = rel
        self.char_start = start
        self.char_end = end


class FakeParser:
    def __init__(self, nodes):
        self.nodes = nodes

    def parse_tree(self, _text):
        return self.nodes


def make_tokens(text, features):
    tokens = []
    for match in re.finditer(r"[\w-]+|[^\w\s]", text):
        word = match.group()
        lemma, pos, entity_id = features.get(word, (word.lower(), "PUNCT", None))
        row = {
            "word": word,
            "clean": word,
            "lemma": lemma,
            "pos": pos,
            "char_start": match.start(),
            "char_end": match.end(),
        }
        if entity_id:
            row["entity_id"] = entity_id
        tokens.append(row)
    return tokens


class SpeechAttributionTests(unittest.TestCase):
    def test_reported_content_has_source_exact_span_and_scoped_roles(self):
        text = "Чацкий сказал, что Фамусов обманывает Софью."
        features = {
            "Чацкий": ("чацкий", "NOUN", "person:chatsky"),
            "сказал": ("сказать", "VERB", None),
            "что": ("что", "NPRO", None),
            "Фамусов": ("фамусов", "NOUN", "person:famusov"),
            "обманывает": ("обманывать", "VERB", None),
            "Софью": ("софья", "NOUN", "person:sofia"),
        }
        tokens = make_tokens(text, features)
        positions = {row["word"]: (row["char_start"], row["char_end"]) for row in tokens}
        nodes = [
            FakeNode(0, "чацкий", "чацкий", "NOUN", 1, "nsubj", *positions["Чацкий"]),
            FakeNode(1, "сказал", "сказать", "VERB", -1, "root", *positions["сказал"]),
            FakeNode(2, "что", "что", "NPRO", 3, "mark", *positions["что"]),
            FakeNode(3, "фамусов", "фамусов", "NOUN", 1, "nsubj", *positions["Фамусов"]),
            FakeNode(4, "обманывает", "обманывать", "VERB", 1, "dep", *positions["обманывает"]),
            FakeNode(5, "софью", "софья", "NOUN", 1, "obj", *positions["Софью"]),
        ]

        result = analyze_speech_structure(
            text, tokens, parser=FakeParser(nodes),
            speech_verbs=frozenset({"сказать"}),
            sub_conjunctions=frozenset({"что"}),
        )

        claims = result["speech_claims"]
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim["mode"], "reported")
        self.assertEqual(claim["source_name"], "Чацкий")
        self.assertEqual(claim["source_entity_id"], "person:chatsky")
        self.assertEqual(
            text[claim["content_char_range"][0]:claim["content_char_range"][1]],
            "что Фамусов обманывает Софью.",
        )
        self.assertEqual(claim["world_status"], "not_assessed")
        self.assertEqual(tokens[3]["speech_scope"]["claim_id"], claim["claim_id"])
        scoped_roles = [
            role for event in result["event_roles"] for role in event["roles"]
            if role["name"] in {"Фамусов", "Софью"}
        ]
        self.assertTrue(scoped_roles)
        self.assertTrue(all(role["scope"] == "reported" for role in scoped_roles))
        self.assertTrue(all(role["source_claim_id"] == claim["claim_id"] for role in scoped_roles))

    def test_negated_reporting_predicate_does_not_assert_complement(self):
        text = "Софья не сказала, что Чацкий приехал."
        features = {
            "Софья": ("софья", "NOUN", "person:sofia"),
            "не": ("не", "PRCL", None),
            "сказала": ("сказать", "VERB", None),
            "что": ("что", "NPRO", None),
            "Чацкий": ("чацкий", "NOUN", "person:chatsky"),
            "приехал": ("приехать", "VERB", None),
        }
        tokens = make_tokens(text, features)
        positions = {row["word"]: (row["char_start"], row["char_end"]) for row in tokens}
        nodes = [
            FakeNode(0, "софья", "софья", "NOUN", 2, "nsubj", *positions["Софья"]),
            FakeNode(1, "не", "не", "PRCL", 2, "advmod:neg", *positions["не"]),
            FakeNode(2, "сказала", "сказать", "VERB", -1, "root", *positions["сказала"]),
            FakeNode(3, "что", "что", "NPRO", 4, "mark", *positions["что"]),
            FakeNode(4, "чацкий", "чацкий", "NOUN", 2, "nsubj", *positions["Чацкий"]),
            FakeNode(5, "приехал", "приехать", "VERB", 2, "dep", *positions["приехал"]),
        ]

        result = analyze_speech_structure(
            text, tokens, parser=FakeParser(nodes),
            speech_verbs=frozenset({"сказать"}),
            sub_conjunctions=frozenset({"что"}),
        )

        self.assertEqual(len(result["speech_claims"]), 1)
        claim = result["speech_claims"][0]
        self.assertEqual(claim["polarity"], "negated_report")
        self.assertEqual(claim["claim_status"], "not_asserted")
        self.assertEqual(claim["world_status"], "not_asserted")
        self.assertEqual(tokens[4]["speech_scope"]["world_status"], "not_asserted")

    def test_direct_turn_is_a_separate_claim_with_turn_evidence(self):
        text = "— Я вернусь."
        tokens = make_tokens(text, {
            "Я": ("я", "NPRO", None),
            "вернусь": ("вернуться", "VERB", None),
        })
        result = analyze_speech_structure(
            text, tokens,
            dialogue_turns=[{
                "turn_id": 4,
                "speaker": "Софья",
                "entity_id": "person:sofia",
                "start_token": 1,
                "end_token": 2,
                "confidence": 1.0,
            }],
            parser=FakeParser([]),
            speech_verbs=frozenset(),
            sub_conjunctions=frozenset(),
        )

        claim = result["speech_claims"][0]
        self.assertEqual(claim["mode"], "direct")
        self.assertEqual(claim["source_name"], "Софья")
        self.assertEqual(claim["source_entity_id"], "person:sofia")
        self.assertEqual(claim["content_token_range"], [1, 2])
        self.assertEqual(tokens[1]["speech_scope"]["claim_id"], "direct-4")

    def test_speech_verb_without_subordinate_clause_is_not_reported_content(self):
        text = "Он говорил о Москве."
        tokens = make_tokens(text, {
            "Он": ("он", "NPRO", None),
            "говорил": ("говорить", "VERB", None),
            "о": ("о", "PREP", None),
            "Москве": ("москва", "NOUN", "place:moscow"),
        })
        positions = {row["word"]: (row["char_start"], row["char_end"]) for row in tokens}
        nodes = [
            FakeNode(0, "он", "он", "NPRO", 1, "nsubj", *positions["Он"]),
            FakeNode(1, "говорил", "говорить", "VERB", -1, "root", *positions["говорил"]),
            FakeNode(2, "о", "о", "PREP", 3, "case", *positions["о"]),
            FakeNode(3, "москве", "москва", "NOUN", 1, "obl:loc", *positions["Москве"]),
        ]
        result = analyze_speech_structure(
            text, tokens, parser=FakeParser(nodes),
            speech_verbs=frozenset({"говорить"}),
            sub_conjunctions=frozenset({"что", "когда"}),
        )

        self.assertEqual(result["speech_claims"], [])
        roles = [role for event in result["event_roles"] for role in event["roles"]]
        self.assertEqual([(role["name"], role["role"]) for role in roles], [("Он", "agent"), ("Москве", "location")])

    def test_world_graph_filter_keeps_only_narrator_scoped_roles(self):
        events = [
            {"predicate": "сказать", "roles": [
                {"name": "Чацкий", "role": "agent", "scope": "narrator"},
                {"name": "Софья", "role": "patient", "scope": "reported"},
            ]},
            {"predicate": "обманывать", "roles": [
                {"name": "Фамусов", "role": "agent", "scope": "direct"},
            ]},
        ]
        result = narrator_event_role_events(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["predicate"], "сказать")
        self.assertEqual([role["name"] for role in result[0]["roles"]], ["Чацкий"])


if __name__ == "__main__":
    unittest.main()
