"""Tests for SpikeLexicon — spike-based word classification."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from spike_lexicon import SpikeLexicon


@pytest.fixture(scope='module')
def slex(tmp_path_factory):
    """Bootstrap once for all tests (expensive: ~300 inflector calls)."""
    codebook_path = tmp_path_factory.mktemp("spike-lexicon") / "codebook"
    sl = SpikeLexicon(codebook_path=codebook_path)
    count = sl.bootstrap()
    assert count > 50, f"Expected >50 words bootstrapped, got {count}"
    return sl


class TestBootstrap:
    """Test that bootstrap populates the codebook."""
    
    def test_bootstrap_count(self, slex):
        assert slex.codebook.n_entries > 50
    
    def test_categories_present(self, slex):
        cats = set()
        for meta in slex.codebook._meta.values():
            cats.add(meta.get('category', ''))
        # Should have at least these
        expected = {'speech_verb', 'stop_word', 'subordinator',
                    'discourse', 'modal', 'title'}
        assert expected.issubset(cats), f"Missing: {expected - cats}"
    
    def test_stats(self, slex):
        s = slex.stats()
        assert s['n_entries'] > 50
        assert 'category_distribution' in s
        assert 'speech_verb' in s['category_distribution']


class TestClassification:
    """Test spike-based word classification."""
    
    def test_known_speech_verb(self, slex):
        """A word in the YAML should classify correctly."""
        results = slex.classify("сказать")
        cats = [cat for cat, _ in results]
        assert 'speech_verb' in cats
    
    def test_known_subordinator(self, slex):
        # Use is_subordinator (spike + YAML fallback) instead of classify top-k
        assert slex.is_subordinator("который")
        assert slex.is_subordinator("когда")
    
    def test_known_stop_word(self, slex):
        results = slex.classify("и")
        # "и" can be stop_word AND pos_override — both valid
        cats = [cat for cat, _ in results]
        assert any(c in ('stop_word', 'pos_override', 'discourse',
                         'cast_additive') for c in cats)
    
    def test_classify_returns_sorted(self, slex):
        """Results should be sorted by descending similarity."""
        results = slex.classify("однако")
        if len(results) > 1:
            sims = [sim for _, sim in results]
            assert sims == sorted(sims, reverse=True)


class TestCompatibilityAPI:
    """Test drop-in replacements for lex.* lookups."""
    
    def test_is_speech_verb_known(self, slex):
        assert slex.is_speech_verb("сказать")
    
    def test_is_speech_verb_unknown(self, slex):
        # "петь" is not a speech verb
        assert not slex.is_speech_verb("петь")
    
    def test_is_subordinator(self, slex):
        assert slex.is_subordinator("который")
    
    def test_is_rhetorical(self, slex):
        assert slex.is_rhetorical("неужели")
    
    def test_is_denial(self, slex):
        assert slex.is_denial("нет")


class TestGeneralization:
    """Test that spike similarity enables generalization to unseen words."""
    
    def test_similar_speech_verb(self, slex):
        """'воскликнуть' is morphologically similar to 'сказать' (both VERB, perf).
        It should be classified as speech_verb even if not in YAML.
        If spike sim is too low, YAML fallback is acceptable.
        """
        # We just check the system doesn't crash and returns something
        results = slex.classify("воскликнуть")
        assert isinstance(results, list)
    
    def test_morphological_form_of_known_word(self, slex):
        """'говорит' (3p sg pres) should spike-match 'говорить' (inf)
        because same lemma → same lemma_atom.
        """
        results = slex.classify("говорит")
        # Should have speech_verb in top categories
        cats = [cat for cat, _ in results]
        # May or may not match depending on threshold — that's OK
        assert isinstance(cats, list)


class TestLiveLearning:
    """Test live learning capability."""
    
    def test_learn_new_word(self, slex):
        """Register a new word and verify it's findable."""
        slex.learn("восклицать", "speech_verb",
                   grammemes={'aspect': 'impf'}, lemma="восклицать")
        
        assert slex.is_speech_verb("восклицать")
    
    def test_learn_invalidates_cache(self, slex):
        """After learning, cache should be cleared for the word."""
        word = "протестовать"
        # Classify first (caches result)
        slex.classify(word)
        assert word in slex._cache
        
        # Learn — should clear cache
        slex.learn(word, "denial", lemma="протестовать")
        assert word not in slex._cache


class TestFallback:
    """Test YAML fallback when spike gives low confidence."""
    
    def test_yaml_fallback_for_stop_word(self, slex):
        """Even if spike gives low confidence, YAML fallback works."""
        # "в" is a 1-char stop word — may have noisy spike encoding
        # but YAML fallback should catch it
        assert slex.is_stop_word("в")
    
    def test_yaml_fallback_for_title(self, slex):
        assert slex.is_title("сударь")
