"""
Loader for Russian linguistic resources from YAML config.

Single source of truth: data/ru/function_words.yaml
All hardcoded linguistic sets in app.py should migrate to use this.

Usage:
    from ru_lexicon import lex
    
    if word in lex.stop_words: ...
    role = lex.discourse_roles.get(word, '')
    override = lex.pos_overrides.get(word)  # → ('CONJ', 'и') or None
"""
import functools
import yaml
from pathlib import Path

_YAML_PATH = Path(__file__).parent / 'data' / 'ru' / 'function_words.yaml'


class RuLexicon:
    """Lazy-loaded, cached Russian lexicon from YAML."""
    
    def __init__(self, path: Path = _YAML_PATH):
        self._path = path
        self._data = None
    
    @property
    def _d(self) -> dict:
        if self._data is None:
            with open(self._path, 'r', encoding='utf-8') as f:
                self._data = yaml.safe_load(f) or {}
        return self._data
    
    # --- Sets ---
    
    @functools.cached_property
    def stop_words(self) -> frozenset:
        return frozenset(self._d.get('stop_words', []))
    
    @functools.cached_property
    def titles(self) -> frozenset:
        return frozenset(self._d.get('titles', []))
    
    @functools.cached_property
    def kinship_markers(self) -> frozenset:
        return frozenset(self._d.get('kinship_markers', []))
    
    @functools.cached_property
    def rhetorical_markers(self) -> frozenset:
        return frozenset(self._d.get('rhetorical_markers', []))
    
    @functools.cached_property
    def speech_verbs(self) -> frozenset:
        return frozenset(self._d.get('speech_verbs', []))
    
    @functools.cached_property
    def title_signals(self) -> frozenset:
        return frozenset(self._d.get('title_signals', []))
    
    @functools.cached_property
    def ironic_markers(self) -> frozenset:
        return frozenset(self._d.get('ironic_markers', []))
    
    @functools.cached_property
    def stage_direction_nouns(self) -> frozenset:
        return frozenset(self._d.get('stage_direction_nouns', []))
    
    @functools.cached_property
    def denial_words(self) -> frozenset:
        return frozenset(self._d.get('denial_words', []))
    
    @functools.cached_property
    def subordinators(self) -> frozenset:
        return frozenset(self._d.get('subordinators', []))
    
    @functools.cached_property
    def clitic_particles(self) -> tuple:
        return tuple(self._d.get('clitic_particles', []))
    
    # --- Suffix tuples ---
    
    @functools.cached_property
    def patronymic_suffixes(self) -> tuple:
        return tuple(self._d.get('patronymic_suffixes', []))
    
    @functools.cached_property
    def surname_suffixes(self) -> tuple:
        return tuple(self._d.get('surname_suffixes', []))
    
    @functools.cached_property
    def masc_surname_suffixes(self) -> tuple:
        return tuple(self._d.get('masc_surname_suffixes', []))
    
    # --- Dicts ---
    
    @functools.cached_property
    def pos_overrides(self) -> dict:
        """word → (POS, lemma) tuple"""
        raw = self._d.get('pos_overrides', {})
        return {k: tuple(v) for k, v in raw.items()}
    
    @functools.cached_property
    def discourse_roles(self) -> dict:
        """conjunction → discourse role string"""
        return dict(self._d.get('discourse_roles', {}))
    
    @functools.cached_property
    def modal_roles(self) -> dict:
        """particle → modal type string"""
        return dict(self._d.get('modal_roles', {}))
    
    @functools.cached_property
    def prep_roles(self) -> dict:
        """preposition → semantic role string"""
        return dict(self._d.get('prep_roles', {}))
    
    # --- Cast connectives (typed) ---
    
    @functools.cached_property
    def cast_ops(self) -> dict:
        """operation_type → frozenset of words"""
        raw = self._d.get('cast_connectives', {})
        return {k: frozenset(v) for k, v in raw.items()}
    
    @functools.cached_property
    def cast_connectives(self) -> frozenset:
        """Flat set of all cast connectives"""
        return frozenset().union(*self.cast_ops.values())
    
    # --- Sentiment ---
    
    @functools.cached_property
    def sentiment_positive(self) -> frozenset:
        return frozenset(self._d.get('sentiment', {}).get('positive', []))
    
    @functools.cached_property
    def sentiment_negative(self) -> frozenset:
        return frozenset(self._d.get('sentiment', {}).get('negative', []))
    
    # --- Pronouns ---
    
    @functools.cached_property
    def pronouns_2per(self) -> frozenset:
        return frozenset(self._d.get('pronouns', {}).get('2per', []))
    
    @functools.cached_property
    def pronouns_3masc(self) -> frozenset:
        return frozenset(self._d.get('pronouns', {}).get('3masc', []))
    
    @functools.cached_property
    def pronouns_3fem(self) -> frozenset:
        return frozenset(self._d.get('pronouns', {}).get('3fem', []))


# Singleton instance
lex = RuLexicon()
