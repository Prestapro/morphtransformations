"""Spike-based lexicon: replaces YAML/frozenset lookups with spike similarity.

Instead of:
    if word in lex.speech_verbs:  # exact match in hardcoded set
        
Uses:
    if spike_lex.classify(word) == 'speech_verb':  # spike similarity
        # Works for unknown words too! "воскликнул" → close to "сказал"

Architecture:
    1. Bootstrap: load function_words.yaml → encode each word via
       JakobsonEncoder → register in SpikeCodebook with category metadata
    2. Classify: encode query word → find nearest in codebook → return category
    3. Live: as new words are processed, they get registered automatically

Graceful degradation: if codebook is empty or similarity too low,
falls back to lex.* (YAML-backed frozenset lookup).

Usage:
    from spike_lexicon import spike_lex
    
    cat = spike_lex.classify("воскликнул")  # → 'speech_verb'
    if spike_lex.is_category("однако", "discourse"):  # → True
    cats = spike_lex.categories("хотя")  # → ['subordinator', 'discourse']

Status: [WORKS]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

# Ensure neuromorph and engine are importable
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

log = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).parent / 'data' / 'ru' / 'function_words.yaml'

# Categories mapped to YAML keys → spike category labels
_CATEGORY_MAP = {
    'stop_words': 'stop_word',
    'titles': 'title',
    'kinship_markers': 'kinship',
    'rhetorical_markers': 'rhetorical',
    'speech_verbs': 'speech_verb',
    'title_signals': 'title_signal',
    'ironic_markers': 'ironic',
    'stage_direction_nouns': 'stage_direction',
    'denial_words': 'denial',
    'subordinators': 'subordinator',
}

# Sentiment and pronouns have nested structure
_NESTED_CATEGORIES = {
    ('sentiment', 'positive'): 'sentiment_positive',
    ('sentiment', 'negative'): 'sentiment_negative',
    ('pronouns', '2per'): 'pronoun_2per',
    ('pronouns', '3masc'): 'pronoun_3masc',
    ('pronouns', '3fem'): 'pronoun_3fem',
}

# Dict-based categories: word → role mapping
_DICT_CATEGORIES = {
    'discourse_roles': 'discourse',
    'modal_roles': 'modal',
    'prep_roles': 'preposition',
}

# Similarity threshold for classification
_DEFAULT_THRESHOLD = 0.30


class SpikeLexicon:
    """Spike-based lexicon wrapping JakobsonEncoder + SpikeCodebook.
    
    On first access, bootstraps the codebook from function_words.yaml.
    Subsequent accesses use spike similarity for word classification.
    """
    
    def __init__(
        self,
        yaml_path: Path = _YAML_PATH,
        threshold: float = _DEFAULT_THRESHOLD,
        codebook_path: Path | None = None,
    ):
        self._yaml_path = yaml_path
        self._threshold = threshold
        self._codebook_path = (
            codebook_path
            if codebook_path is not None
            else Path(__file__).parent / "data" / "spike_codebook"
        )
        self._encoder = None
        self._codebook = None
        self._bootstrapped = False
        self._inflector = None
        # Cache: word → list of (category, similarity) for fast repeat lookups
        self._cache: dict[str, list[tuple[str, float]]] = {}
        # Fallback: the original YAML lex
        self._lex = None
    
    @property
    def encoder(self):
        if self._encoder is None:
            from neuromorph.morphir.jakobson import JakobsonEncoder
            self._encoder = JakobsonEncoder(lemma_dim=256)
        return self._encoder
    
    @property
    def codebook(self):
        if self._codebook is None:
            from neuromorph.memory.spike_codebook import SpikeCodebook
            self._codebook = SpikeCodebook(
                d_spike=self.encoder.total_dim,  # 270
                path=self._codebook_path,
            )
        return self._codebook
    
    @property
    def lex(self):
        """Fallback YAML lexicon."""
        if self._lex is None:
            from ru_lexicon import lex
            self._lex = lex
        return self._lex
    
    def _get_inflector(self):
        """Lazy inflector import."""
        if self._inflector is None:
            try:
                from engine.language.inflector import analyze
                self._inflector = analyze
            except ImportError:
                self._inflector = lambda w: []
        return self._inflector
    
    # ══════════════════════════════════════
    # Bootstrap
    # ══════════════════════════════════════
    
    def bootstrap(self, force: bool = False) -> int:
        """Load function_words.yaml → encode each word → register in codebook.
        
        Returns number of words registered.
        """
        if self._bootstrapped and not force:
            return self.codebook.n_entries
        
        import yaml
        with open(self._yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        count = 0
        analyze = self._get_inflector()
        
        # Simple list categories
        for yaml_key, cat_label in _CATEGORY_MAP.items():
            words = data.get(yaml_key, [])
            if isinstance(words, list):
                for word in words:
                    if self._register_word(word, cat_label, analyze):
                        count += 1
        
        # Nested categories
        for (parent_key, child_key), cat_label in _NESTED_CATEGORIES.items():
            words = data.get(parent_key, {}).get(child_key, [])
            if isinstance(words, list):
                for word in words:
                    if self._register_word(word, cat_label, analyze):
                        count += 1
        
        # Dict categories (word → role)
        for yaml_key, cat_label in _DICT_CATEGORIES.items():
            word_map = data.get(yaml_key, {})
            if isinstance(word_map, dict):
                for word, role in word_map.items():
                    meta_extra = {'role': role}
                    if self._register_word(word, cat_label, analyze,
                                           extra_meta=meta_extra):
                        count += 1
        
        # Cast connectives (nested dict: type → [words])
        cast = data.get('cast_connectives', {})
        if isinstance(cast, dict):
            for op_type, words in cast.items():
                if isinstance(words, list):
                    for word in words:
                        if self._register_word(word, f'cast_{op_type}',
                                               analyze):
                            count += 1
        
        # POS overrides (word → [POS, lemma])
        overrides = data.get('pos_overrides', {})
        if isinstance(overrides, dict):
            for word, val in overrides.items():
                if isinstance(val, list) and len(val) == 2:
                    meta_extra = {'pos_override': val[0], 'lemma_override': val[1]}
                    if self._register_word(word, 'pos_override', analyze,
                                           extra_meta=meta_extra):
                        count += 1
        
        self._bootstrapped = True
        self.codebook.save()
        log.info(f'SpikeLexicon bootstrapped: {count} words in codebook')
        return count
    
    def _register_word(self, word: str, category: str,
                       analyze_fn, extra_meta: dict = None) -> bool:
        """Encode and register one word."""
        try:
            word = word.strip().lower()
            if not word:
                return False
            
            # Get grammemes from inflector
            grammemes = {}
            lemma = word
            pos = 'UNKN'
            
            parses = analyze_fn(word)
            if parses:
                p = parses[0]
                lemma = p.lemma if hasattr(p, 'lemma') else word
                pos = p.pos if hasattr(p, 'pos') else 'UNKN'
                # Extract grammemes
                for attr in ('case', 'number', 'gender', 'animacy',
                             'aspect', 'tense', 'voice', 'mood', 'person'):
                    val = getattr(p, attr, None)
                    if val:
                        grammemes[attr] = val
            
            # Encode via Jakobson
            vec = self.encoder.encode_word(word, lemma, grammemes)
            
            # Build metadata
            meta = {
                'lemma': lemma,
                'pos': pos,
                'category': category,
            }
            meta.update(grammemes)
            if extra_meta:
                meta.update(extra_meta)
            
            # Check if already registered with this category AND non-zero vector
            import mlx.core as mx
            existing = self.codebook._meta.get(word, {})
            if existing.get('category') == category:
                # Verify stored vector is not corrupted (all-zeros)
                stored = self.codebook._entries.get(word)
                if stored is not None and int(mx.sum(stored != 0)) > 0:
                    return False
                # Zero vector: re-register with good vector
            
            # Register (word may have multiple categories → use word:cat as key)
            key = f'{word}:{category}' if word in self.codebook._entries else word
            
            import mlx.core as mx
            self.codebook.register(key, mx.array(vec, dtype=mx.float32), meta)
            return True
            
        except Exception as e:
            log.debug(f'Failed to register {word}: {e}')
            return False
    
    # ══════════════════════════════════════
    # Classification
    # ══════════════════════════════════════
    
    def _ensure_bootstrapped(self):
        """Bootstrap on first use if needed."""
        if not self._bootstrapped and self.codebook.n_entries == 0:
            self.bootstrap()
    
    def classify(self, word: str, top_k: int = 3) -> list[tuple[str, float]]:
        """Classify a word by spike similarity.
        
        Two-tier strategy:
        1. Full vector (270d) for exact/near-exact match
        2. POS+morphology match for category generalization (content words)
        
        Returns list of (category, similarity) sorted by descending similarity.
        """
        self._ensure_bootstrapped()
        
        word_lower = word.strip().lower()
        
        # Cache check
        if word_lower in self._cache:
            return self._cache[word_lower]
        
        # Encode query word
        analyze = self._get_inflector()
        grammemes = {}
        lemma = word_lower
        pos = 'UNKN'
        
        parses = analyze(word_lower)
        if parses:
            p = parses[0]
            lemma = p.lemma if hasattr(p, 'lemma') else word_lower
            pos = p.pos if hasattr(p, 'pos') else 'UNKN'
            for attr in ('case', 'number', 'gender', 'animacy',
                         'aspect', 'tense', 'voice', 'mood', 'person'):
                val = getattr(p, attr, None)
                if val:
                    grammemes[attr] = val
        
        import mlx.core as mx
        
        # Tier 1: Full vector match (finds exact word or close inflection)
        vec = self.encoder.encode_word(word_lower, lemma, grammemes)
        full_vec = mx.array(vec, dtype=mx.float32)
        try:
            matches = self.codebook.recognize(full_vec, top_k=top_k * 3)
        except ValueError as e:
            # Codebook has entries with mismatched dimensions — log once
            if not getattr(self, '_shape_error_logged', False):
                self._shape_error_logged = True
                # Diagnostic: find which entries have wrong shape
                shapes = {}
                for k, v in self.codebook._entries.items():
                    s = tuple(v.shape)
                    shapes.setdefault(s, []).append(k)
                shape_summary = {str(s): len(keys) for s, keys in shapes.items()}
                print(f"[WARN] spike_lexicon.classify: codebook shape mismatch — {e}")
                print(f"[DIAG] Entry shapes: {shape_summary}")
                print(f"[DIAG] query shape: {full_vec.shape}, expected uniform shape across all entries")
            return []
        
        cat_scores: dict[str, float] = {}
        
        # Process Tier 1
        for match_key, sim in matches:
            meta = self.codebook._meta.get(match_key, {})
            cat = meta.get('category', 'unknown')
            if sim > self._threshold:
                cat_scores[cat] = max(cat_scores.get(cat, 0), sim)
        
        # Tier 2: POS-based category transfer (content words only)
        # If word is a verb and we have verb-category entries, transfer category
        _CONTENT_POS = {'VERB', 'INFN', 'NOUN', 'ADJF', 'ADJS', 'ADVB',
                        'PRTF', 'PRTS', 'GRND'}
        
        if pos in _CONTENT_POS and (not cat_scores or max(cat_scores.values()) < 0.5):
            # Tier 2: POS-filtered full-vector similarity
            # Within the same POS group, compare full 270d vectors 
            # (14d gram + 256d lemma hash). Lemma hash discriminates
            # between different lexical subclasses within a POS.
            gram_vec = mx.array(
                self.encoder.encode_grammemes(grammemes), dtype=mx.float32
            )
            
            # Collect POS-matching neighbors with full-vector similarity
            neighbors: list[tuple[str, float]] = []  # (category, full_sim)
            
            for key, entry_vec in self.codebook._entries.items():
                meta = self.codebook._meta.get(key, {})
                entry_pos = meta.get('pos', 'UNKN')
                cat = meta.get('category', 'unknown')
                
                # POS group match
                pos_match = False
                if pos in ('VERB', 'INFN', 'GRND', 'PRTF', 'PRTS'):
                    pos_match = entry_pos in ('VERB', 'INFN', 'GRND',
                                               'PRTF', 'PRTS')
                elif pos in ('NOUN',):
                    pos_match = entry_pos == 'NOUN'
                elif pos in ('ADJF', 'ADJS'):
                    pos_match = entry_pos in ('ADJF', 'ADJS')
                elif pos == 'ADVB':
                    pos_match = entry_pos == 'ADVB'
                
                if not pos_match:
                    continue
                
                # Full 270d cosine similarity (gram 14d + lemma 256d)
                e_vec = entry_vec.astype(mx.float32)
                e_norm = float(mx.linalg.norm(e_vec))
                q_norm = float(mx.linalg.norm(full_vec))
                
                if q_norm > 1e-6 and e_norm > 1e-6:
                    sim = float(mx.sum(full_vec * e_vec)) / (q_norm * e_norm)
                else:
                    sim = 0.0
                
                if sim > 0.3:
                    neighbors.append((cat, sim))
            
            # Take top-k neighbors and check category consistency
            if len(neighbors) >= 3:
                neighbors.sort(key=lambda x: -x[1])
                top_n = neighbors[:min(7, len(neighbors))]
                
                cat_counts: dict[str, int] = {}
                cat_best_sim: dict[str, float] = {}
                for cat, sim in top_n:
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    cat_best_sim[cat] = max(cat_best_sim.get(cat, 0), sim)
                
                for cat, count in cat_counts.items():
                    ratio = count / len(top_n)
                    # Require majority AND decent similarity
                    if ratio >= 0.5 and cat_best_sim[cat] > 0.4:
                        score = 0.25 + cat_best_sim[cat] * 0.35 * ratio
                        if score > cat_scores.get(cat, 0):
                            cat_scores[cat] = score
        
        result = sorted(cat_scores.items(), key=lambda x: -x[1])[:top_k]
        
        # Cache
        self._cache[word_lower] = result
        return result
    
    def best_category(self, word: str) -> Optional[str]:
        """Return the single best category or None if below threshold."""
        results = self.classify(word, top_k=1)
        if results and results[0][1] >= self._threshold:
            return results[0][0]
        return None
    
    def is_category(self, word: str, category: str) -> bool:
        """Check if word belongs to a specific category.
        
        Example:
            spike_lex.is_category("сказал", "speech_verb")  # → True
            spike_lex.is_category("однако", "discourse")    # → True
        """
        results = self.classify(word, top_k=5)
        for cat, sim in results:
            if cat == category and sim >= self._threshold:
                return True
        return False
    
    # ══════════════════════════════════════
    # Compatibility API (drop-in for lex.*)
    # ══════════════════════════════════════
    
    def is_speech_verb(self, word: str) -> bool:
        """Spike-based: is this a speech verb?
        Falls back to lex.speech_verbs if codebook gives low confidence.
        """
        if self.is_category(word, 'speech_verb'):
            return True
        return word.strip().lower() in self.lex.speech_verbs
    
    def is_subordinator(self, word: str) -> bool:
        if self.is_category(word, 'subordinator'):
            return True
        return word.strip().lower() in self.lex.subordinators
    
    def is_rhetorical(self, word: str) -> bool:
        if self.is_category(word, 'rhetorical'):
            return True
        return word.strip().lower() in self.lex.rhetorical_markers
    
    def is_stop_word(self, word: str) -> bool:
        if self.is_category(word, 'stop_word'):
            return True
        return word.strip().lower() in self.lex.stop_words
    
    def is_title(self, word: str) -> bool:
        if self.is_category(word, 'title'):
            return True
        return word.strip().lower() in self.lex.titles
    
    def is_kinship(self, word: str) -> bool:
        if self.is_category(word, 'kinship'):
            return True
        return word.strip().lower() in self.lex.kinship_markers
    
    def is_ironic(self, word: str) -> bool:
        if self.is_category(word, 'ironic'):
            return True
        return word.strip().lower() in self.lex.ironic_markers
    
    def is_denial(self, word: str) -> bool:
        if self.is_category(word, 'denial'):
            return True
        return word.strip().lower() in self.lex.denial_words
    
    def is_title_signal(self, word: str) -> bool:
        """Spike-based: work-type nouns (роман, повесть, пьеса)."""
        if self.is_category(word, 'title_signal'):
            return True
        return word.strip().lower() in self.lex.title_signals
    
    def is_sentiment_positive(self, word: str) -> bool:
        if self.is_category(word, 'sentiment_positive'):
            return True
        return word.strip().lower() in self.lex.sentiment_positive
    
    def is_sentiment_negative(self, word: str) -> bool:
        if self.is_category(word, 'sentiment_negative'):
            return True
        return word.strip().lower() in self.lex.sentiment_negative
    
    def is_stage_direction_noun(self, word: str) -> bool:
        if self.is_category(word, 'stage_direction'):
            return True
        return word.strip().lower() in self.lex.stage_direction_nouns
    
    def get_discourse_role(self, word: str) -> Optional[str]:
        """Get discourse role for a word. Spike-first, YAML-fallback."""
        results = self.classify(word, top_k=3)
        for cat, sim in results:
            if cat == 'discourse' and sim >= self._threshold:
                # Get the role from metadata of the best match
                matches = self.codebook.recognize(
                    self._encode_quick(word), top_k=1
                )
                if matches:
                    meta = self.codebook._meta.get(matches[0][0], {})
                    return meta.get('role')
        return self.lex.discourse_roles.get(word.strip().lower())
    
    def get_modal_role(self, word: str) -> Optional[str]:
        results = self.classify(word, top_k=3)
        for cat, sim in results:
            if cat == 'modal' and sim >= self._threshold:
                matches = self.codebook.recognize(
                    self._encode_quick(word), top_k=1
                )
                if matches:
                    meta = self.codebook._meta.get(matches[0][0], {})
                    return meta.get('role')
        return self.lex.modal_roles.get(word.strip().lower())
    
    def get_prep_role(self, word: str) -> Optional[str]:
        results = self.classify(word, top_k=3)
        for cat, sim in results:
            if cat == 'preposition' and sim >= self._threshold:
                matches = self.codebook.recognize(
                    self._encode_quick(word), top_k=1
                )
                if matches:
                    meta = self.codebook._meta.get(matches[0][0], {})
                    return meta.get('role')
        return self.lex.prep_roles.get(word.strip().lower())
    
    def _encode_quick(self, word: str):
        """Quick encode for repeated lookups (no inflector)."""
        import mlx.core as mx
        vec = self.encoder.encode_word(word.lower(), word.lower(), {})
        return mx.array(vec, dtype=mx.float32)
    
    # ══════════════════════════════════════
    # Live learning
    # ══════════════════════════════════════
    
    def learn(self, word: str, category: str,
              grammemes: dict = None, lemma: str = None) -> None:
        """Register a new word with a category (live learning).
        
        Called when the system encounters a word and determines its
        category through context (e.g., it's used as a speech verb).
        """
        import mlx.core as mx
        lemma = lemma or word.strip().lower()
        grammemes = grammemes or {}
        vec = self.encoder.encode_word(word.lower(), lemma, grammemes)
        meta = {'lemma': lemma, 'category': category}
        meta.update(grammemes)
        self.codebook.register(word.lower(), mx.array(vec, dtype=mx.float32), meta)
        # Invalidate cache for this word
        self._cache.pop(word.strip().lower(), None)
    
    # ══════════════════════════════════════
    # Stats
    # ══════════════════════════════════════
    
    def stats(self) -> dict:
        """Report codebook stats."""
        self._ensure_bootstrapped()
        base = self.codebook.stats()
        # Count by category
        cat_counts: dict[str, int] = {}
        for meta in self.codebook._meta.values():
            cat = meta.get('category', 'unknown')
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        base['category_distribution'] = cat_counts
        return base


# ══════════════════════════════════════
# Singleton
# ══════════════════════════════════════

spike_lex = SpikeLexicon()
