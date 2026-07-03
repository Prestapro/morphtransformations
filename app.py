import sys
import re
import sqlite3
import math
import traceback
import json
import yaml
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Configuration & Constants ---
PARENT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PARENT_DIR / 'data' / 'language' / 'ru_paradigms.sqlite3'
SUFFIX_DB_PATH = PARENT_DIR / 'data' / 'language' / 'suffix_model.sqlite3'
STATIC_DIR = PARENT_DIR / "morphtransformations" / "static"
TIKHONOV_PATH = PARENT_DIR / "data" / "tikhonov_morphemes.json"
LOGIC_TRIGGERS_PATH = PARENT_DIR / "neuromorph" / "data" / "linguistic" / "logic_triggers.yaml"

# Add engine to path for MorphemeAlgebra
sys.path.append(str(PARENT_DIR))
from engine.hdc.morpheme_algebra import MorphemeAlgebra
from engine.narrative.stylometry import compute_stylometry
from engine.narrative.plot_analysis import analyze_text as analyze_plot
from engine.narrative.scene_detector import detect_scene_boundaries
from engine.reasoning.text_structure import analyze_thematic_progression
from engine.language.inflector import analyze as inflector_analyze
from ru_lexicon import lex

STOP_WORDS = lex.stop_words
TITLES = lex.titles
KINSHIP_MARKERS = lex.kinship_markers

# --- Linguistic Operator Registry ---
class LinguisticOperatorRegistry:
    def __init__(self, yaml_path: Path):
        self.operators = {} # lemma -> type
        if yaml_path.exists():
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                # Parse pragmatics
                if 'pragmatics' in data:
                    for op_type, words in data['pragmatics'].items():
                        for w in words: self.operators[w.lower()] = op_type
                # Parse connectives
                if 'connectives' in data:
                    for op_type, words in data['connectives'].items():
                        for w in words: 
                            if w.lower() not in self.operators:
                                self.operators[w.lower()] = "logic"
                # Parse probability markers
                if 'probability_markers' in data:
                    for prob, words in data['probability_markers'].items():
                        for w in words: self.operators[w.lower()] = "modal"

    def get_type(self, lemma: str) -> Optional[str]:
        return self.operators.get(lemma.lower())

# --- Repository Layer ---
class KnowledgeBase:
    def __init__(self, db_path: Path, suffix_path: Path, tikhonov_path: Path):
        self.db_path = db_path
        self.suffix_path = suffix_path
        self.tikhonov_path = tikhonov_path
        self._paradigm_cache = {}
        self._morpheme_cache = {}
        self._suffix_cache = {}
        self._roots_index = None # Lazy load
        self.morph_algebra = MorphemeAlgebra()

    @contextmanager
    def _get_conn(self, path: Path):
        conn = sqlite3.connect(str(path))
        try: yield conn
        finally: conn.close()

    def _load_tikhonov(self):
        if self._roots_index is not None: return
        if self.tikhonov_path.exists():
            with open(self.tikhonov_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._roots_index = data.get('roots_index', {})
        else:
            self._roots_index = {}

    def prefetch(self, words: List[str]):
        search_words = []
        for w in words:
            if not w.isalnum(): continue
            low = w.lower(); search_words.append(low)
            if 'е' in low: search_words.append(low.replace('е', 'ё'))
            if 'ё' in low: search_words.append(low.replace('ё', 'е'))
        unique_search = list(set(search_words))
        if not unique_search: return
        with self._get_conn(self.db_path) as conn:
            c = conn.cursor()
            placeholders = ','.join(['?'] * len(unique_search))
            c.execute(f"SELECT form, lemma, grammemes FROM paradigms WHERE form IN ({placeholders})", unique_search)
            for f, l, g in c.fetchall():
                if f not in self._paradigm_cache: self._paradigm_cache[f] = []
                self._paradigm_cache[f].append({"lemma": l, "grams": g})
        with self._get_conn(self.suffix_path) as conn:
            sc = conn.cursor()
            suffixes = list(set(w.lower()[-3:] for w in unique_search if len(w) >= 3))
            if suffixes:
                s_placeholders = ','.join(['?'] * len(suffixes))
                sc.execute(f"SELECT suffix, probability FROM suffix_stats WHERE suffix IN ({s_placeholders})", suffixes)
                for s, p in sc.fetchall(): self._suffix_cache[s] = p

    def get_info(self, word: str):
        w = word.lower(); res = self._paradigm_cache.get(w)
        if not res and 'е' in w: res = self._paradigm_cache.get(w.replace('е', 'ё'))
        return res or []

    def get_best_lemma(self, word: str, preferred_gender: Optional[str] = None):
        info = self.get_info(word)
        if not info: return word.capitalize(), None
        best_entry = info[0]
        for entry in info:
            if any(x in entry['grams'] for x in ['Name', 'Surn', 'Patr', 'anim']):
                if not preferred_gender or preferred_gender in entry['grams']:
                    best_entry = entry; break
        gender = 'femn' if 'femn' in best_entry['grams'] else 'masc'
        return best_entry['lemma'].capitalize(), gender

    def get_h_morph(self, word: str) -> float:
        """Calculates true H_morph: log2(candidates with the same root)"""
        self._load_tikhonov()
        try:
            decomposition = self.morph_algebra.decompose(word)
        except Exception:
            decomposition = []
            
        root = None
        if decomposition:
            for m_type, m_val in decomposition:
                if m_type == "ROOT":
                    root = m_val
                    break
        
        if not root:
            # Fallback: entropy of morpheme count
            return round(math.log2(len(word) // 3 + 1), 2)
        
        candidates = self._roots_index.get(root, [])
        count = len(candidates)
        if count == 0: return round(math.log2(len(word) // 3 + 1), 2)
        return round(math.log2(count), 2)

    def get_suffix_prob(self, word: str): return self._suffix_cache.get(word.lower()[-3:], None)

# --- Sentiment Engine ---
class SentimentEngine:
    def __init__(self):
        self.pos = lex.sentiment_positive
        self.neg = lex.sentiment_negative

    def get_score(self, word: str) -> float:
        w = word.lower()
        if w in self.pos: return 1.0
        if w in self.neg: return -1.0
        return 0.0

# --- NER Engine ---
class NEREngine:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def classify_candidate(self, token: str) -> Dict[str, Any]:
        if not token or not token[0].isupper() or token.lower() in STOP_WORDS: return {"type": "noise", "confidence": 0.0}
        low = token.lower()
        if low in TITLES: return {"type": "title", "confidence": 0.8}
        if low in KINSHIP_MARKERS: return {"type": "kinship", "confidence": 0.9}
        
        info = self.kb.get_info(token)
        if not info:
            if low.endswith(('ович', 'евна', 'овна', 'ична')): return {"type": "person", "confidence": 0.95}
            if low.endswith(('ов', 'ин', 'ский')): return {"type": "person", "confidence": 0.6}
            return {"type": "unknown_capitalized", "confidence": 0.3}
        confidence = 0.0; etype = "unknown"; is_animate = False
        for entry in info:
            g = entry['grams']
            if any(x in g for x in ['Name', 'Surn', 'Patr']): confidence += 0.8; is_animate = True; etype = "person"
            if 'anim' in g: is_animate = True; confidence += 0.15
            if 'Geox' in g: etype = "place"; confidence += 0.2
        if etype == "person" and is_animate: confidence = max(confidence, 0.85)
        return {"type": etype, "confidence": min(1.0, confidence)}

# --- API ---
app = FastAPI(title="Logos Full Spectrum Engine", version="5.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
kb = KnowledgeBase(DB_PATH, SUFFIX_DB_PATH, TIKHONOV_PATH)
operators = LinguisticOperatorRegistry(LOGIC_TRIGGERS_PATH)

class TensionMapRequest(BaseModel):
    text: str

# --- Genre Detection ---
def detect_genre(text: str) -> str:
    """Classify text as prose / verse_drama / poetry."""
    lines = [l for l in text.split('\n') if l.strip()]
    if len(lines) < 3:
        return 'prose'
    avg_len = sum(len(l.strip()) for l in lines) / len(lines)
    # ALL-CAPS Cyrillic names on their own lines (ФАМУСОВ, ЧАЦКИЙ)
    caps_names = sum(1 for l in lines if re.match(r'^[А-ЯЁ]{2,}[А-ЯЁ\s]*(?:\s*\(.*\))?\s*$', l.strip()))
    has_caps_names = caps_names >= 2
    short_lines = sum(1 for l in lines if 3 < len(l.strip()) < 65)
    short_ratio = short_lines / len(lines)
    # Stage directions in parentheses
    has_parens = sum(1 for l in lines if '(' in l and ')' in l) >= 1
    
    if has_caps_names and short_ratio > 0.5 and (avg_len < 55 or has_parens):
        return 'verse_drama'
    elif avg_len < 45 and short_ratio > 0.7 and not has_caps_names:
        return 'poetry'
    return 'prose'


# --- 3rd person pronoun coreference helper ---
def _find_last_entity_by_gender(results, current_idx, target_gender, known_speakers, current_speaker):
    """Find the last mentioned entity before current_idx that matches target_gender.
    
    target_gender: 'masc' or 'fem'
    Returns entity name or None.
    """
    # Scan backwards up to 100 tokens
    search_limit = max(0, current_idx - 100)
    candidates = []
    
    for j in range(current_idx - 1, search_limit, -1):
        r = results[j]
        # Look for entities and speaker names
        name = None
        if r.get('is_entity') and r.get('confidence', 0) >= 0.6:
            name = r.get('clean', r['word'])
        elif r['word'] in known_speakers:
            name = r['word']
        elif r.get('line_type') == 'SPEAKER':
            name = r['word']
        # Capitalized word in TEXT context → likely proper noun (entity candidate)
        elif (r.get('line_type') == 'TEXT' and r['word'][0:1].isupper() 
              and len(r['word']) > 1 and r['word'][1:].islower()
              and r['word'].isalpha()):
            # Exclude sentence-initial words (preceded by sentence-ending punct)
            if j > 0 and results[j-1]['word'] not in ('.', '!', '?', '…'):
                name = r['word']
        
        if not name or name == current_speaker or ' ' in name:
            continue
        
        # Determine gender from inflector (with surname correction)
        try:
            parses = inflector_analyze(name)
            if parses:
                gender = getattr(parses[0], 'gender', None)
                # Fix: Russian masculine surnames (-ов/-ев/-ин/-ский/-ый/-ой/-ий)
                # get misparsed as femn by inflector
                name_lower = name.lower()
                if gender == 'femn':
                    masc_suffixes = ('ов', 'ев', 'ёв', 'ин', 'ын', 'ский', 'ской', 'цкий', 'цкой', 'ый', 'ой', 'ий')
                    if any(name_lower.endswith(s) for s in masc_suffixes):
                        gender = 'masc'
                
                if gender == 'masc' and target_gender == 'masc':
                    return name
                elif gender in ('femn',) and target_gender == 'fem':
                    return name
                elif gender and ((gender == 'masc') != (target_gender == 'masc')):
                    continue  # wrong gender, skip
                
                # Fallback: no reliable gender — use ending heuristic
                if target_gender == 'fem' and (name_lower.endswith('а') or name_lower.endswith('я')):
                    return name
                elif target_gender == 'masc' and not (name_lower.endswith('а') or name_lower.endswith('я')):
                    return name
        except Exception:
            pass
    
    return None


# --- Text Depth Metrics ---
def compute_depth_metrics(tokens_data: list, window_size: int = 15) -> dict:
    """Compute text depth metrics across 3 axes + coherence.
    
    Axes:
      1. Lexical richness: TTR × surprisal (log-inverse frequency)
      2. Semantic dimensionality: effective rank of lemma co-occurrence vectors
      3. Structural depth: clause nesting (subordinators, participles, relative pronouns)
    
    Plus coherence: sliding window Jaccard similarity.
    
    Args:
        tokens_data: list of token dicts from analysis (must have 'word', 'lemma')
        window_size: size of sliding windows for coherence/semantic analysis
    
    Returns:
        dict with keys: lexical, semantic, structural, coherence, composite, 
              per_window (list of per-window composite scores)
    """
    import math
    
    # Extract TEXT-only tokens
    text_tokens = [t for t in tokens_data 
                   if t.get('line_type', 'TEXT') == 'TEXT' and t['word'].isalpha()]
    
    if len(text_tokens) < 5:
        return {'lexical': 0.0, 'semantic': 0.0, 'structural': 0.0,
                'coherence': 0.0, 'composite': 0.0, 'per_window': []}
    
    words = [t['word'].lower() for t in text_tokens]
    lemmas = []
    for t in text_tokens:
        lem = t.get('lemma', t['word'].lower())
        if not lem:
            lem = t['word'].lower()
        lemmas.append(lem)
    
    # === Axis 1: Lexical Richness ===
    n = len(words)
    n_types = len(set(lemmas))
    ttr = n_types / n if n > 0 else 0
    
    # Surprisal: -log(freq) averaged. Use corpus-relative frequency.
    freq = {}
    for w in lemmas:
        freq[w] = freq.get(w, 0) + 1
    # Average surprisal: higher = more surprising = richer vocabulary
    surprisal_vals = [-math.log2(freq[w] / n) for w in lemmas]
    avg_surprisal = sum(surprisal_vals) / len(surprisal_vals) if surprisal_vals else 0
    # Normalize surprisal to [0, 1] range (log2(n) is max possible)
    max_surprisal = math.log2(n) if n > 1 else 1
    norm_surprisal = min(avg_surprisal / max_surprisal, 1.0) if max_surprisal > 0 else 0
    
    lexical = ttr * (0.5 + 0.5 * norm_surprisal)  # TTR weighted by surprisal
    
    # Hapax ratio as bonus
    n_hapax = sum(1 for v in freq.values() if v == 1)
    hapax_ratio = n_hapax / n_types if n_types > 0 else 0
    lexical = lexical * (0.7 + 0.3 * hapax_ratio)  # boost for many unique words
    
    # === Axis 2: Semantic Dimensionality ===
    # Approximate PCA rank via lemma co-occurrence diversity
    # Count how many distinct lemma-pairs co-occur in windows
    windows = []
    for i in range(0, len(lemmas), window_size // 2):
        w = set(lemmas[i:i + window_size])
        if len(w) >= 3:
            windows.append(w)
    
    if len(windows) >= 2:
        # Count distinct topics: how many windows have < 50% overlap?
        distinct_windows = 1
        for i in range(1, len(windows)):
            overlap = len(windows[i] & windows[i-1]) / max(len(windows[i] | windows[i-1]), 1)
            if overlap < 0.5:
                distinct_windows += 1
        # Normalize: log scale (1 topic = 0, 8+ topics = 1.0)
        semantic = min(math.log2(distinct_windows + 1) / 3.0, 1.0)
    else:
        semantic = 0.0
    
    # === Axis 3: Structural Depth ===
    # Count subordinating signals: relative pronouns, conjunctions, participles
    subordinators = {'который', 'которая', 'которое', 'которые', 'которого', 'которой',
                     'что', 'чтобы', 'если', 'хотя', 'когда', 'потому', 'поскольку',
                     'пока', 'чем', 'где', 'куда', 'откуда', 'насколько', 'ибо'}
    
    n_subordinators = 0
    n_participles = 0
    for t in text_tokens:
        lem = t.get('lemma', t['word'].lower())
        if lem in subordinators:
            n_subordinators += 1
        # Participles and gerunds indicate structural embedding
        pos = t.get('pos', '')
        if pos in ('PRTF', 'PRTS', 'GRND'):
            n_participles += 1
    
    # Also: average sentence length variation (complex = varying lengths)
    sent_lengths = []
    curr_len = 0
    for t in tokens_data:
        if t['word'] in ('.', '!', '?', '…'):
            if curr_len > 0:
                sent_lengths.append(curr_len)
            curr_len = 0
        elif t['word'].isalpha():
            curr_len += 1
    if curr_len > 0:
        sent_lengths.append(curr_len)
    
    if sent_lengths and len(sent_lengths) > 1:
        avg_len = sum(sent_lengths) / len(sent_lengths)
        std_len = (sum((x - avg_len)**2 for x in sent_lengths) / len(sent_lengths)) ** 0.5
        cv = std_len / avg_len if avg_len > 0 else 0  # coefficient of variation
    else:
        cv = 0
    
    # Structural = subordination density + syntactic variation
    sub_density = min((n_subordinators + n_participles * 0.5) / max(n, 1) * 10, 1.0)
    struct_variation = min(cv / 0.8, 1.0)  # CV=0.8 → max complexity
    structural = sub_density * 0.6 + struct_variation * 0.4
    
    # === Coherence ===
    # Sliding window Jaccard similarity between adjacent windows
    similarities = []
    if len(windows) >= 2:
        for i in range(len(windows) - 1):
            intersection = len(windows[i] & windows[i+1])
            union = len(windows[i] | windows[i+1])
            sim = intersection / union if union > 0 else 0
            similarities.append(sim)
        coherence = sum(similarities) / len(similarities)
    else:
        coherence = 1.0  # single window = coherent by default
    
    # === Composite ===
    # Multiplicative: all axes must be present for true depth
    # Add floor of 0.1 to avoid zeroing out the product
    composite = ((lexical + 0.1) * (semantic + 0.1) * (structural + 0.1) * 
                 (coherence + 0.1))
    # Normalize to [0, 1]: max possible = 1.1^4 = 1.4641
    composite = min(composite / 1.4641, 1.0)
    
    # === Per-window depth ===
    per_window = []
    for i, win in enumerate(windows):
        w_ttr = len(win) / window_size if window_size > 0 else 0
        w_coh = similarities[i] if i < len(similarities) else coherence
        per_window.append(round(w_ttr * w_coh, 3))
    
    return {
        'lexical': round(lexical, 3),
        'semantic': round(semantic, 3),
        'structural': round(structural, 3),
        'coherence': round(coherence, 3),
        'composite': round(composite, 3),
        'per_window': per_window,
    }


# --- Text Structural Segmentation ---
def segment_text(text: str, tokens: list, entity_map: dict) -> list:
    """Segment text into structural blocks using engine analysis.
    
    Returns list of boundary markers:
      {after_token: int, type: str, level: int, reason: str}
    
    Types: heading, act, scene, paragraph, dialogue_turn
    Levels: 0=sentence, 1=paragraph, 2=scene, 3=act/chapter
    """
    segments = []
    
    # --- Pass 1: Heading detection by FORM (language-agnostic) ---
    # A heading line is detected by its visual/typographic properties:
    #   - Short (≤ 6 words)
    #   - ALL CAPS or Title Case
    #   - No sentence-ending punctuation (no . , ; : at end)
    #   - Preceded by blank line or start of text
    #   - May contain a numeral (ordinal, roman, arabic)
    
    def _classify_line(line: str, prev_blank: bool, next_line: str = '') -> tuple:
        """Classify a line by typographic form (language-agnostic).
        
        Returns:
            (type, level) where type is one of:
            'heading'         (3) — structural heading (ДЕЙСТВИЕ ПЕРВОЕ, Chapter 3)
            'speaker'         (2) — speaker label (ФАМУСОВ, ЧАЦКИЙ, or "Name:")
            'characters_line' (2) — cast list (Лиза и Фамусов)
            'stage_direction' (0) — stage direction (в скобках)
            (None, 0)              — not a structural marker
        """
        s = line.strip()
        if not s:
            return (None, 0)
        
        # ── Stage direction: starts with ( ──
        # Covers "(входит стремительно)", "(aside)", "(Тушит свечу.)"
        if s.startswith('(') and (s.endswith(')') or s.endswith(').') or ')' in s):
            return ('stage_direction', 0.99)  # bracketed = unambiguous
        # Standalone closing paren from multi-line stage direction
        if s == ')':
            return ('stage_direction', 0.95)  # closing paren
        
        # Below this: only short lines (≤80 chars, ≤8 words)
        if len(s) > 80:
            return (None, 0)
        words = re.findall(r'[\w]+', s)
        if not words:
            return (None, 0)
        # Allow longer lines if they contain parenthetical stage directions
        max_words = 14 if '(' in s and ')' in s else 8
        if len(words) > max_words:
            return (None, 0)
        
        # ── Speaker with colon: "ФАМУСОВ:" or "Charles:" ──
        if s.endswith(':') and len(words) <= 3:
            return ('speaker', 0.95)  # has explicit colon
        
        # ── Unbracketed stage directions inside turns ──
        # "Обнимаются.", "Садятся.", "Молчание.", "Уходит." — no parentheses
        # Short line (1-3 words), ends with '.', uses inflector for morphological detection
        if len(words) <= 3 and s.endswith('.'):
            # Check via inflector: any word is VERB with person=3per
            is_stage_verb = False
            for w in words:
                clean_w = w.rstrip('.')
                if not clean_w or not clean_w[0].isalpha():
                    continue
                try:
                    parses = inflector_analyze(clean_w)
                    if parses:
                        p = parses[0]
                        if p.pos == 'VERB' and getattr(p, 'person', None) == '3per':
                            is_stage_verb = True
                            break
                except Exception:
                    pass
            
            # Fallback: stage direction nouns (not morphologically verb-like)
            _STAGE_NOUNS = lex.stage_direction_nouns
            lower_set = {w.lower().rstrip('.') for w in words}
            if is_stage_verb or (lower_set & _STAGE_NOUNS):
                return ('stage_direction', 0.85)  # inflector: VERB+3per or stage noun
        
        has_numeral = bool(re.search(r'\d+|[IVXLC]{1,6}$', s))
        all_caps = s.rstrip(':') == s.rstrip(':').upper() and any(c.isalpha() for c in s)
        alpha_words = [w for w in words if w[0].isalpha()]
        title_case = len(alpha_words) >= 2 and all(w[0].isupper() for w in alpha_words)
        ends_with_punct = s[-1] in '.,:;!?…'
        
        # ── Speaker detection (works even without prev_blank) ──
        # Strict punctuation filter: internal commas, semicolons etc. disqualify
        # This prevents "Барин, да." from triggering as speaker
        _SPEAKER_BAD_CHARS = set(',;!?—–«»""\u201c\u201d()…:')
        has_bad_punct = any(c in _SPEAKER_BAD_CHARS for c in s.rstrip('.'))
        
        # Speaker with colon already handled above (line ~278)
        
        # Single CAPS word = speaker (ФАМУСОВ)
        if (all_caps and len(words) == 1 and not has_numeral 
                and not ends_with_punct and not has_bad_punct):
            return ('speaker', 0.95 if prev_blank else 0.85)  # CAPS word
        
        # Single Title Case word = speaker (Чацкий, Sofia, Молчалин)
        # Next line must exist and be either text or stage direction
        if (len(words) == 1 and not all_caps and not has_numeral 
                and not ends_with_punct and not has_bad_punct
                and words[0][0].isupper()
                and next_line
                and (next_line.startswith('(') or len(next_line.split()) > 1 or next_line != next_line.strip().title())):
            return ('speaker', 0.90 if prev_blank else 0.80)  # Title Case, needs next_line
        
        # Must be preceded by blank line for remaining structural markers
        # (headings — these require more context).
        # Exception: characters_line can follow a heading directly without blank.
        
        # ── Characters line: names with connectives or commas ──
        # "Лиза и Фамусов", "София, Лиза и Молчалин", "Romeo and Juliet"
        # "София, Лиза, Чацкий, Фамусов." — comma-separated, may end with '.'
        # "Фамусов, Чацкий (смотрит на дверь)." — names + parenthetical = cast+stage
        
        # Strip parenthetical content for name analysis
        s_bare = re.sub(r'\([^)]*\)', '', s).strip().rstrip('.')
        bare_words = re.findall(r'[\w]+', s_bare)
        bare_alpha = [w for w in bare_words if w[0].isalpha()]
        
        cap_words = [w for w in bare_alpha if w[0].isupper()]
        lower_words = [w for w in bare_words if w[0].islower()]
        has_comma = ',' in s_bare
        has_question = '?' in s_bare
        has_parens = '(' in s
        s_stripped = s_bare.rstrip('.')  # allow trailing period
        
        # Cast connectives classified by semantic operation (from YAML)
        _CAST_CONNECTIVES = lex.cast_connectives
        
        # Characters line: ≥2 capitalized words, connected by commas/connectives
        # Reject if: has '?', ends with '!' or '…', has too many non-name words
        if (len(cap_words) >= 2 and not has_numeral and not has_question
                and 2 <= len(bare_alpha) <= 8 and not all_caps
                and (has_comma or lower_words)  # commas OR connectives like "и"
                and not s_stripped.endswith(('!', '…'))):
            # Check: do all alpha words (outside parens) look like proper nouns?
            all_names = all(w[0].isupper() for w in bare_alpha)
            if all_names and has_comma:
                # "София, Лиза, Чацкий, Фамусов." or 
                # "Фамусов, Чацкий (смотрит на дверь)."
                return ('characters_line', 0.90)
            elif lower_words:
                # Only if ALL lowercase words are connectives, not verbs/adverbs
                non_connective = [w for w in lower_words if w.lower() not in _CAST_CONNECTIVES]
                if not non_connective:
                    return ('characters_line', 0.85)  # names with connectives
        
        if not prev_blank:
            return (None, 0)
        
        # ── Multi-word CAPS or CAPS+numeral = structural heading ──
        if all_caps and (len(words) >= 2 or has_numeral) and not ends_with_punct:
            return ('heading', 0.95)  # multi-word CAPS
        
        # ── Title Case + numeral = structural heading (Chapter 3, Явление 10) ──
        # Single capitalized word + numeral counts (not just multi-word Title Case)
        if has_numeral and not ends_with_punct and alpha_words and all(w[0].isupper() for w in alpha_words):
            return ('heading', 0.90)  # Title Case + numeral
        
        return (None, 0)
    
    # Build sentence list from tokens for scene_detector
    sentences = []
    sent_start_tokens = []  # token index where each sentence starts
    current_sent_words = []
    current_start = 0
    entities_per_sentence = []
    current_entities = set()
    
    for i, t in enumerate(tokens):
        current_sent_words.append(t)
        ent = entity_map.get(i)
        if ent and ent['confidence'] >= 0.6:
            current_entities.add(ent['canonical'])
        
        if t in '.!?…' and i < len(tokens) - 1:
            sentences.append(' '.join(current_sent_words))
            sent_start_tokens.append(current_start)
            entities_per_sentence.append(current_entities)
            current_sent_words = []
            current_start = i + 1
            current_entities = set()
    
    if current_sent_words:
        sentences.append(' '.join(current_sent_words))
        sent_start_tokens.append(current_start)
        entities_per_sentence.append(current_entities)
    
    # Scan lines and classify each one
    lines = text.split('\n')
    line_start_token = 0
    line_type_map = {}  # token_index → line_type (HEADER|SPEAKER|STAGE_DIRECTION|CHARACTERS_LINE|TEXT)
    line_type_conf_map = {}  # token_index → confidence (0.0-1.0) from _classify_line
    prev_blank = True  # start of text counts as preceded by blank
    for li, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            prev_blank = True
            continue
        
        # Find next non-blank line (skip blanks between speaker and text)
        next_line = ''
        for nli in range(li + 1, len(lines)):
            nl_stripped = lines[nli].strip()
            if nl_stripped:
                next_line = nl_stripped
                break
        ltype, lconf = _classify_line(stripped, prev_blank, next_line)
        
        line_tok_count = len(re.findall(r'[\w-]+|[^\w\s]', stripped))
        
        # Map line_type for all tokens on this line
        lt = 'TEXT'
        lt_conf = 0.5  # default for TEXT
        if ltype == 'heading':
            lt = 'HEADER'
            lt_conf = lconf
        elif ltype == 'speaker':
            lt = 'SPEAKER'
            lt_conf = lconf
        elif ltype == 'stage_direction':
            lt = 'STAGE_DIRECTION'
            lt_conf = lconf
        elif ltype == 'characters_line':
            lt = 'CHARACTERS_LINE'
            lt_conf = lconf
        
        for ti in range(line_start_token, line_start_token + line_tok_count):
            if ti < len(tokens):
                line_type_map[ti] = lt
                line_type_conf_map[ti] = lt_conf
        
        # Detect inline stage directions: tokens inside () within TEXT or CHARACTERS_LINE
        if lt in ('TEXT', 'CHARACTERS_LINE'):
            in_paren = False
            for ti in range(line_start_token, min(line_start_token + line_tok_count, len(tokens))):
                if tokens[ti] == '(':
                    in_paren = True
                    line_type_map[ti] = 'STAGE_DIRECTION'
                elif tokens[ti] == ')' and in_paren:
                    line_type_map[ti] = 'STAGE_DIRECTION'
                    in_paren = False
                elif in_paren:
                    line_type_map[ti] = 'STAGE_DIRECTION'
        
        if ltype:
            line_tokens = re.findall(r'[\w-]+|[^\w\s]', stripped)
            if line_tokens:
                for ti in range(line_start_token, min(len(tokens), line_start_token + 20)):
                    if ti < len(tokens) and tokens[ti].upper() == line_tokens[0].upper():
                        segments.append({
                            'after_token': max(0, ti - 1),
                            'type': ltype,
                            'level': int(lconf * 3) if ltype == 'heading' else int(lconf * 2),  # legacy compat
                            'confidence': lconf,
                            'reason': f'form:{stripped[:40]}'
                        })
                        break
        
        line_start_token += line_tok_count
        # Headings and stage directions act as structural separators
        prev_blank = ltype in ('heading', 'stage_direction', 'characters_line') if ltype else False
    
    # --- Pass 1.5: Rhythm-based heading detection ---
    # Detects structural headings by form, not by language-specific keywords.
    # Pattern types:
    #   A) word + number/ordinal, repeating prefix ≥2  ("Явление 1", "Chapter 3")
    #   B) section dividers: ***, ---, ===, * * *
    #   C) repeated exact short line without number ≥2  ("Антракт" ×3)
    #   D) isolated short line with length contrast to surrounding text
    
    from collections import Counter
    
    _NUM_RE = re.compile(r'^\d+$|^[IVXLCDM]{1,8}$')
    _NUM_ANYWHERE = re.compile(r'\d+|[IVXLC]{1,6}')
    _ORDINAL_SUFFIX = re.compile(r'(?:st|nd|rd|th|ое|ая|ий|ый|ой)$', re.I)
    _DIVIDER_RE = re.compile(r'^[\s*\-=~_·•]{3,}$')
    
    # Collect known speakers/entities to filter them out
    known_speakers = set()
    for s in segments:
        if s['type'] == 'speaker':
            known_speakers.add(s.get('reason', '').replace('form:', '').strip().lower())
    known_entities = {e['canonical'].lower() for e in entity_map.values() if e['confidence'] >= 0.6}
    speaker_filter = known_speakers | known_entities
    
    # Pre-compute line word counts for length contrast
    line_word_counts = []
    for line in lines:
        s = line.strip()
        line_word_counts.append(len(re.findall(r'[\w]+', s)) if s else 0)
    
    rhythm_candidates = []  # unified candidate list
    line_start_tok2 = 0
    
    for li, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        wds = re.findall(r'[\w]+', stripped)
        line_tok_count = len(re.findall(r'[\w-]+|[^\w\s]', stripped))
        
        # Check isolation: blank line before (or start of text)
        prev_blank = li == 0 or (li > 0 and not lines[li - 1].strip())
        
        # --- Pattern B: Section dividers ---
        if _DIVIDER_RE.match(stripped) and len(stripped) >= 3:
            rhythm_candidates.append({
                'pattern': 'divider',
                'prefix': '_divider',
                'key': stripped[:3],  # group similar dividers
                'line_idx': li,
                'text': stripped,
                'tok_start': line_start_tok2
            })
            line_start_tok2 += line_tok_count
            continue
        
        # Only short lines (1-4 words) for heading candidates
        ends_with_punct = stripped[-1] in '.!?…' if stripped else False
        
        if 1 <= len(wds) <= 4 and not ends_with_punct:
            has_num = bool(_NUM_ANYWHERE.search(stripped))
            has_ordinal = any(_ORDINAL_SUFFIX.search(w) for w in wds)
            is_all_caps = stripped == stripped.upper() and any(c.isalpha() for c in stripped)
            is_solo_number = len(wds) == 1 and _NUM_RE.match(wds[0])
            line_lower = stripped.lower()
            is_speaker_name = line_lower in speaker_filter or (is_all_caps and len(wds) == 1)
            
            if has_num or has_ordinal:
                # --- Pattern A: word + number ---
                prefix_parts = []
                for w in wds:
                    if _NUM_RE.match(w) or _ORDINAL_SUFFIX.search(w):
                        break
                    prefix_parts.append(w.lower())
                prefix = ' '.join(prefix_parts) if prefix_parts else '_solo_number'
                rhythm_candidates.append({
                    'pattern': 'word_number',
                    'prefix': prefix,
                    'key': prefix,
                    'line_idx': li,
                    'text': stripped,
                    'tok_start': line_start_tok2,
                    'is_solo_number': is_solo_number
                })
            elif not is_speaker_name and prev_blank:
                # --- Pattern C: short line without number, not a speaker ---
                # --- Pattern D: isolated with length contrast ---
                # Compute local median word count (±5 non-empty lines)
                nearby = [c for c in line_word_counts[max(0,li-10):li+10] if c > 0]
                median_nearby = sorted(nearby)[len(nearby)//2] if nearby else 0
                contrast = median_nearby / max(len(wds), 1)
                
                rhythm_candidates.append({
                    'pattern': 'short_isolated',
                    'prefix': '_exact:' + line_lower,
                    'key': line_lower,
                    'line_idx': li,
                    'text': stripped,
                    'tok_start': line_start_tok2,
                    'contrast': contrast
                })
        
        line_start_tok2 += line_tok_count
    
    # --- Confirm by repetition ---
    key_counts = Counter(c['key'] for c in rhythm_candidates)
    existing_seg_toks = {s['after_token'] for s in segments}
    
    for c in rhythm_candidates:
        tok_idx = c['tok_start']
        after_tok = max(0, tok_idx - 1) if tok_idx > 0 else 0
        
        # Skip if already segmented nearby
        if any(abs(after_tok - et) < 3 for et in existing_seg_toks):
            continue
        
        emit = False
        reason = ''
        seg_type = 'heading'
        seg_level = 3
        
        if c['pattern'] == 'divider':
            emit = True
            reason = f'divider:{c["text"][:10]}'
            seg_type = 'divider'
            seg_level = 2
        
        elif c['pattern'] == 'word_number':
            count = key_counts[c['key']]
            if count >= 2:
                emit = True
                reason = f'rhythm:{c["prefix"]}×{count}'
            elif c.get('is_solo_number') and key_counts['_solo_number'] >= 2:
                emit = True
                reason = f'rhythm:number×{key_counts["_solo_number"]}'
        
        elif c['pattern'] == 'short_isolated':
            count = key_counts[c['key']]
            if count >= 2:
                # Exact text repeats ≥2 times as isolated short line
                emit = True
                reason = f'rhythm_exact:{c["text"][:20]}×{count}'
            elif c.get('contrast', 0) >= 5:
                # Single occurrence but extreme length contrast to surroundings
                emit = True
                reason = f'contrast:{c["contrast"]:.1f}×'
        
        if emit:
            segments.append({
                'after_token': after_tok,
                'type': seg_type,
                'level': seg_level,
                'reason': reason
            })
            existing_seg_toks.add(after_tok)
    
    # --- Pass 2: Scene boundaries (entity change + temporal markers) ---
    # Use high threshold + wide window to avoid marking every speaker change
    # as a scene break. Within one "явление", speaker changes are dialogue, not scenes.
    heading_positions = {s['after_token'] for s in segments if s['type'] == 'heading'}
    
    if len(sentences) >= 5:
        try:
            locations = [None] * len(sentences)
            boundaries = detect_scene_boundaries(
                sentences, entities_per_sentence, locations,
                threshold=0.65, window=5
            )
            for b in boundaries:
                if b.after_sentence < len(sent_start_tokens) - 1:
                    tok_idx = sent_start_tokens[b.after_sentence + 1] - 1
                    # Suppress if too close to a heading (same structural unit)
                    near_heading = any(abs(tok_idx - hp) < 30 for hp in heading_positions)
                    if near_heading:
                        continue
                    # Only emit if entity change is strong (not just one speaker swap)
                    if b.entity_change < 0.7 and not b.temporal_gap:
                        continue
                    segments.append({
                        'after_token': tok_idx,
                        'type': 'scene',
                        'level': 2,
                        'reason': b.reason,
                        'score': round(b.score, 3)
                    })
        except Exception as e:
            print(f'Scene detection failed: {e}')
    
    # --- Pass 3: Paragraph boundaries from whitespace ---
    pos = 0
    for i, t in enumerate(tokens):
        idx = text.find(t, pos)
        if idx >= 0:
            gap = text[pos:idx]
            if '\n\n' in gap and i > 0:
                # Check it's not already marked
                already = any(s['after_token'] == i - 1 for s in segments)
                if not already:
                    segments.append({
                        'after_token': i - 1,
                        'type': 'paragraph',
                        'level': 1,
                        'reason': 'whitespace'
                    })
            pos = idx + len(t)
    
    # --- Pass 4: Dialogue turns (— after .!?) ---
    for i, t in enumerate(tokens):
        if t == '—' and i > 0 and tokens[i-1] in '.!?…»"':
            already = any(abs(s['after_token'] - (i-1)) <= 1 for s in segments)
            if not already:
                segments.append({
                    'after_token': i - 1,
                    'type': 'dialogue_turn',
                    'level': 1,
                    'reason': 'dash_after_punct'
                })
    
    # --- Pass 5: Thematic progression (Level 4) ---
    try:
        thematic = analyze_thematic_progression(text)
        # Stored for inspector, not used for segmentation directly
    except Exception:
        thematic = None
    
    # --- Pass 2.5: Prose dialogue parser integration ---
    # If no structural speaker labels found, try prose parser
    structural_speakers = [s for s in segments if s['type'] == 'speaker']
    if len(structural_speakers) < 2:
        try:
            # dialogue_parser.py is in same directory as app.py (morphtransformations/)
            _dp_dir = str(Path(__file__).parent)
            if _dp_dir not in sys.path:
                sys.path.insert(0, _dp_dir)
            from dialogue_parser import DialogueParser, detect_format as dp_detect_format
            from dialogue_parser import TextFormat
            
            fmt = dp_detect_format(text)
            if fmt in (TextFormat.PROSE_EM, TextFormat.PROSE_Q, TextFormat.MIXED):
                parser = DialogueParser()
                prose_turns = parser.parse(text)
                
                if prose_turns:
                    # Strategy: for each prose turn with a speaker, find the 
                    # em-dash that starts the turn's speech in the token stream.
                    # Approach: scan tokens for the speaker's name near attribution verb,
                    # then trace back to the preceding em-dash.
                    
                    # Build a set of used positions to avoid duplicates
                    used_positions = set()
                    
                    for turn in prose_turns:
                        if not turn.speaker or turn.speaker in ('UNKNOWN', 'narrator'):
                            continue
                        
                        # Find the speaker name in the token stream
                        spk_name = turn.speaker
                        for ti, tok in enumerate(tokens):
                            if tok == spk_name and ti not in used_positions:
                                # Found the speaker name — find the nearest preceding em-dash
                                dash_pos = None
                                for j in range(ti - 1, max(ti - 10, -1), -1):
                                    if j >= 0 and tokens[j] == '—':
                                        dash_pos = j
                                        break
                                
                                if dash_pos is not None:
                                    # The turn starts at the em-dash BEFORE this one
                                    # (em-dash before the speech, not the attribution dash)
                                    # Look further back for the speech-starting dash
                                    speech_dash = None
                                    for j in range(dash_pos - 1, max(dash_pos - 20, -1), -1):
                                        if j >= 0 and tokens[j] == '—':
                                            speech_dash = j
                                            break
                                    
                                    target_pos = speech_dash if speech_dash is not None else dash_pos
                                    if target_pos not in used_positions:
                                        used_positions.add(target_pos)
                                        used_positions.add(ti)
                                        segments.append({
                                            'after_token': max(0, target_pos - 1),
                                            'type': 'speaker',
                                            'level': 2,
                                            'reason': f'form:{spk_name}',
                                            'confidence': 0.80,
                                            'source_format': fmt.value,
                                        })
                                        break  # found this speaker, move to next turn
        except ImportError:
            pass  # dialogue_parser not available
        except Exception as e:
            print(f'Prose parser integration failed: {e}')
    
    # --- Pass 2.6: Unattributed em-dash dialogue fallback ---
    # If still no speakers found, detect em-dash dialogue lines
    # and assign alternating pseudo-speakers (Голос A / Голос B)
    structural_speakers_after = [s for s in segments if s['type'] == 'speaker']
    if len(structural_speakers_after) < 2:
        # Find which tokens start lines beginning with em-dash
        # by scanning the original text line-by-line
        lines = text.split('\n')
        dash_lines = []  # (line_index, stripped_line) for lines starting with '—'
        for li, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('—'):
                dash_lines.append(li)
        
        if len(dash_lines) >= 2:
            # Find the token indices for each dash-line's '—'
            # Strategy: track which line each token belongs to
            # by matching original text positions
            dash_turn_starts = []
            
            # Rebuild line → token index mapping from text positions
            # Tokenizer splits text into tokens; we need to find '—' tokens
            # that correspond to dash_lines
            line_start_chars = []
            pos = 0
            for line in lines:
                line_start_chars.append(pos)
                pos += len(line) + 1  # +1 for \n
            
            for dl_idx in dash_lines:
                line_char_start = line_start_chars[dl_idx]
                # Find the '—' token at or near this character position
                for ti, tok in enumerate(tokens):
                    if tok == '—' and ti not in dash_turn_starts:
                        # Check: is this token near the line start?
                        # Simple: scan by token position in text
                        tok_pos = text.find('—', line_char_start)
                        if tok_pos is not None and tok_pos < line_char_start + 5:
                            dash_turn_starts.append(ti)
                            break
            
            if len(dash_turn_starts) >= 2:
                # Alternating speakers: A, B, A, B, ...
                _PSEUDO_SPEAKERS = ['Голос A', 'Голос B']
                for idx, dash_pos in enumerate(dash_turn_starts):
                    spk = _PSEUDO_SPEAKERS[idx % 2]
                    segments.append({
                        'after_token': max(0, dash_pos),
                        'type': 'speaker',
                        'level': 2,
                        'reason': f'form:{spk}',
                        'confidence': 0.60,
                        'source_format': 'prose_em_unattributed',
                    })
                    line_type_map[dash_pos] = 'SPEAKER'
                    line_type_conf_map[dash_pos] = 0.60
    # Sort by position, deduplicate (keep highest level)
    segments.sort(key=lambda s: (s['after_token'], -s['level']))
    
    # Deduplicate: at same position, keep highest level
    deduped = []
    seen_positions = set()
    for s in segments:
        if s['after_token'] not in seen_positions:
            deduped.append(s)
            seen_positions.add(s['after_token'])
    
    # --- Pass 3: Morphological boundary signals ---
    # Detect person/number shifts between consecutive TEXT lines via inflector.
    # These are EVIDENCE signals (not new turn boundaries) — they confirm or
    # question existing structural boundaries.
    # Type 1 boundary (discourse break): person shift IS a real signal
    # Type 2 boundary (within monologue): person shift may be false positive
    morph_boundary_signals = []
    try:
        line_profiles = []  # [{line_idx, first_tok, persons: set, numbers: set, moods: set}]
        _line_start = 0
        for li, line in enumerate(text.split('\n')):
            stripped = line.strip()
            _line_tok_count = len(re.findall(r'[\w-]+|[^\w\s]', stripped)) if stripped else 0
            if stripped and line_type_map.get(_line_start) == 'TEXT':
                persons = set()
                moods = set()
                for ti in range(_line_start, min(_line_start + _line_tok_count, len(tokens))):
                    tok = tokens[ti]
                    if not tok[0].isalpha():
                        continue
                    parses = inflector_analyze(tok)
                    if parses:
                        p = parses[0]
                        pers = getattr(p, 'person', None)
                        mood = getattr(p, 'mood', None)
                        pos = getattr(p, 'pos', None)
                        if pers and pos in ('VERB', 'NPRO'):
                            persons.add(pers)
                        if mood and pos == 'VERB':
                            moods.add(mood)
                if persons:
                    line_profiles.append({
                        'line_idx': li, 'first_tok': _line_start,
                        'persons': persons, 'moods': moods
                    })
            _line_start += _line_tok_count
        
        # Detect shifts between consecutive profiled lines
        for i in range(1, len(line_profiles)):
            prev_p = line_profiles[i-1]
            curr_p = line_profiles[i]
            prev_persons = prev_p['persons']
            curr_persons = curr_p['persons']
            
            # Person shift: e.g., {2per} → {1per}
            if prev_persons and curr_persons and not prev_persons.intersection(curr_persons):
                shift_strength = 0.6  # base signal
                # Stronger if clear deictic swap: 1per↔2per
                if ('1per' in prev_persons and '2per' in curr_persons) or \
                   ('2per' in prev_persons and '1per' in curr_persons):
                    shift_strength = 0.8
                # Mood shift (imperative→indicative) adds evidence
                if prev_p['moods'] and curr_p['moods'] and not prev_p['moods'].intersection(curr_p['moods']):
                    shift_strength = min(1.0, shift_strength + 0.15)
                
                morph_boundary_signals.append({
                    'after_token': max(0, curr_p['first_tok'] - 1),
                    'type': 'morph_boundary',
                    'confidence': shift_strength,
                    'reason': f'person_shift:{",".join(sorted(prev_persons))}→{",".join(sorted(curr_persons))}',
                    'prev_line': prev_p['line_idx'],
                    'curr_line': curr_p['line_idx'],
                })
    except Exception as e:
        print(f'Morph boundary pass failed: {e}')
    
    # --- Pass 4: KL-divergence boundary signals ---
    # Distributional shift detection: compare lexical distribution in
    # sliding windows before/after each position. JSD peak = candidate
    # for speaker change (different "voice" = different word distribution).
    # Uses Jensen-Shannon Divergence (bounded 0-1) instead of raw KL.
    kl_boundary_signals = []
    try:
        import math
        _KL_WINDOW = 15  # tokens per window (larger for Russian morphology)
        _JSD_ZSCORE = 1.0  # z-scores above mean to register as signal
        _MIN_GAP = 8  # minimum tokens between reported peaks
        
        # Build lemmatized token stream (only alpha tokens from TEXT lines)
        lemma_stream = []  # [(original_tok_idx, lemma)]
        for ti, tok in enumerate(tokens):
            if not tok[0].isalpha():
                continue
            lt = line_type_map.get(ti, 'TEXT')
            if lt not in ('TEXT',):
                continue
            # Lemmatize via inflector
            parses = inflector_analyze(tok)
            lemma = parses[0].lemma if parses and hasattr(parses[0], 'lemma') else tok.lower()
            lemma_stream.append((ti, lemma))
        
        def _jsd(before_lemmas, after_lemmas):
            """Jensen-Shannon Divergence (symmetric, bounded [0, ln2])."""
            from collections import Counter as _C
            p_cnt = _C(before_lemmas)
            q_cnt = _C(after_lemmas)
            vocab = set(p_cnt) | set(q_cnt)
            n_p = len(before_lemmas)
            n_q = len(after_lemmas)
            
            # Build probability distributions with Laplace smoothing
            v = len(vocab)
            p = {w: (p_cnt.get(w, 0) + 1) / (n_p + v) for w in vocab}
            q = {w: (q_cnt.get(w, 0) + 1) / (n_q + v) for w in vocab}
            
            # M = (P + Q) / 2
            m = {w: (p[w] + q[w]) / 2.0 for w in vocab}
            
            # JSD = (KL(P||M) + KL(Q||M)) / 2
            kl_pm = sum(p[w] * math.log(p[w] / m[w]) for w in vocab if p[w] > 0)
            kl_qm = sum(q[w] * math.log(q[w] / m[w]) for w in vocab if q[w] > 0)
            
            jsd = (kl_pm + kl_qm) / 2.0
            # Normalize to [0, 1] by dividing by ln(2)
            return jsd / math.log(2)
        
        if len(lemma_stream) >= _KL_WINDOW * 2:
            jsd_scores = []  # (stream_pos, jsd_value, tok_idx)
            
            for split in range(_KL_WINDOW, len(lemma_stream) - _KL_WINDOW + 1):
                before = [l for _, l in lemma_stream[split - _KL_WINDOW:split]]
                after = [l for _, l in lemma_stream[split:split + _KL_WINDOW]]
                
                jsd = _jsd(before, after)
                tok_idx = lemma_stream[split][0]
                jsd_scores.append((split, jsd, tok_idx))
            
            # Find peaks using z-score (relative to text's distribution)
            jsd_values = [j for _, j, _ in jsd_scores]
            jsd_mean = sum(jsd_values) / len(jsd_values)
            jsd_std = (sum((j - jsd_mean)**2 for j in jsd_values) / len(jsd_values))**0.5
            jsd_threshold = jsd_mean + _JSD_ZSCORE * jsd_std if jsd_std > 0 else jsd_mean * 1.5
            
            peaks = []
            for i in range(1, len(jsd_scores) - 1):
                _, jsd, tok_idx = jsd_scores[i]
                if jsd > jsd_threshold:
                    _, jsd_prev, _ = jsd_scores[i-1]
                    _, jsd_next, _ = jsd_scores[i+1]
                    if jsd >= jsd_prev and jsd >= jsd_next:  # local maximum
                        peaks.append((tok_idx, jsd))
            
            # Enforce minimum gap between peaks (keep strongest)
            filtered_peaks = []
            for tok_idx, jsd in peaks:
                if filtered_peaks and tok_idx - filtered_peaks[-1][0] < _MIN_GAP:
                    # Keep the stronger peak
                    if jsd > filtered_peaks[-1][1]:
                        filtered_peaks[-1] = (tok_idx, jsd)
                else:
                    filtered_peaks.append((tok_idx, jsd))
            
            for tok_idx, jsd in filtered_peaks:
                # Map confidence from z-score: z=1→0.55, z=2→0.75, z=3+→0.95
                z = (jsd - jsd_mean) / jsd_std if jsd_std > 0 else 1.0
                conf = min(0.95, 0.45 + z * 0.15)
                kl_boundary_signals.append({
                    'after_token': max(0, tok_idx - 1),
                    'type': 'kl_boundary',
                    'confidence': round(conf, 3),
                    'kl_value': round(jsd, 4),
                    'z_score': round(z, 2),
                    'reason': f'jsd:{jsd:.3f}(z={z:.1f})',
                })
    except Exception as e:
        print(f'KL boundary pass failed: {e}')
    
    # --- Pass 5: Evidence fusion ---
    # Combine all 3 detectors into unified boundary_evidence.
    # When multiple detectors agree at the same position (±2 tokens),
    # fuse their confidences: 1 - Π(1 - ci) (Noisy-OR).
    boundary_evidence = {}  # token_idx → {sources: [...], fused_confidence: float}
    
    # Collect all signals by position (structural boundaries from segments)
    all_signals = []
    for s in deduped:
        if s['type'] == 'speaker':
            all_signals.append(('structural', s['after_token'], s.get('confidence', 0.9)))
    for mb in morph_boundary_signals:
        all_signals.append(('morph', mb['after_token'], mb['confidence']))
    for kb in kl_boundary_signals:
        all_signals.append(('jsd', kb['after_token'], kb['confidence']))
    
    # Group by position (±2 tokens = same boundary)
    for source, pos, conf in sorted(all_signals, key=lambda x: x[1]):
        # Find if there's already a boundary within ±2 tokens
        matched = None
        for existing_pos in boundary_evidence:
            if abs(existing_pos - pos) <= 2:
                matched = existing_pos
                break
        
        if matched is not None:
            be = boundary_evidence[matched]
            be['sources'].append({'type': source, 'position': pos, 'confidence': conf})
            # Noisy-OR fusion: P(boundary) = 1 - Π(1 - ci)
            be['fused_confidence'] = 1.0 - (1.0 - be['fused_confidence']) * (1.0 - conf)
        else:
            boundary_evidence[pos] = {
                'after_token': pos,
                'sources': [{'type': source, 'position': pos, 'confidence': conf}],
                'fused_confidence': conf,
                'n_detectors': 0,  # filled below
            }
    
    # Count unique detector types and mark consensus
    for pos, be in boundary_evidence.items():
        detector_types = set(s['type'] for s in be['sources'])
        be['n_detectors'] = len(detector_types)
        be['detector_types'] = list(detector_types)
        be['consensus'] = len(detector_types) >= 2  # 2+ detectors agree
    
    # --- Build speech turns ---
    # Walk segments to assign speaker/turn_id to every token.
    # Speaker segment at token T → all tokens from T+1 until next speaker/heading
    # belong to that speaker's turn.
    speaker_map = {}  # token_index → {'speaker': str, 'turn_id': int}
    
    # Collect speaker boundaries sorted by position
    speaker_segs = [(s['after_token'], s) for s in deduped 
                    if s['type'] in ('speaker', 'heading', 'characters_line')]
    speaker_segs.sort(key=lambda x: x[0])
    
    if speaker_segs:
        turn_id = 0
        for si in range(len(speaker_segs)):
            seg_tok = speaker_segs[si][0]
            seg = speaker_segs[si][1]
            
            if seg['type'] != 'speaker':
                # Headings/cast lines reset the speaker
                turn_id += 1
                continue
            
            # Extract speaker name from reason
            speaker_name = seg.get('reason', '').replace('form:', '').strip()
            
            # Find actual speaker token (first SPEAKER-typed token at or after seg_tok)
            speaker_tok = None
            for ti in range(seg_tok, min(seg_tok + 5, len(tokens))):
                if line_type_map.get(ti) == 'SPEAKER':
                    speaker_tok = ti
                    break
            if speaker_tok is None:
                speaker_tok = seg_tok  # fallback
            
            # Token range: from speaker_tok to next speaker/heading seg
            if si + 1 < len(speaker_segs):
                end_tok = speaker_segs[si + 1][0]
                # Find actual start of next segment (skip trailing punct from our turn)
                # The end_tok points to after_token of next seg — include trailing punct in current turn
                # by extending to include it
                if end_tok < len(tokens) and line_type_map.get(end_tok) == 'TEXT' and tokens[end_tok] in '.?!…;:':
                    end_tok += 1  # include trailing punct in current turn
            else:
                end_tok = len(tokens)
            
            # Get confidence from speaker line classification
            spk_conf = line_type_conf_map.get(speaker_tok, 0.8)
            # Mark the speaker name token
            speaker_map[speaker_tok] = {'speaker': speaker_name, 'turn_id': turn_id, 'is_speaker_label': True, 'speaker_confidence': spk_conf}
            # Mark all tokens in this turn (skip HEADER tokens, start after speaker token)
            for ti in range(speaker_tok + 1, end_tok):
                if line_type_map.get(ti) != 'HEADER':
                    speaker_map[ti] = {'speaker': speaker_name, 'turn_id': turn_id, 'is_speaker_label': False, 'speaker_confidence': spk_conf}
            
            turn_id += 1
    
    # --- Pass 6: Error recovery ---
    # Retroactive correction hints based on evidence disagreement.
    # Not modifying speaker_map directly — injecting correction_hints
    # that downstream can use.
    for pos, be in boundary_evidence.items():
        be['correction_hint'] = None
        
        # Case 1: JSD-only boundary (no structural) → might be missed speaker
        if be['n_detectors'] >= 1 and 'structural' not in be['detector_types']:
            # Check if there's a morph signal too
            if 'morph' in be['detector_types'] and be['fused_confidence'] > 0.7:
                be['correction_hint'] = 'possible_missed_speaker'
            elif be['fused_confidence'] > 0.6:
                be['correction_hint'] = 'weak_boundary_signal'
        
        # Case 2: Structural boundary with very low confidence + no confirmation
        if 'structural' in be['detector_types'] and be['n_detectors'] == 1:
            # Find the structural source
            for src in be['sources']:
                if src['type'] == 'structural' and src['confidence'] < 0.85:
                    be['correction_hint'] = 'unconfirmed_structural'
                    break
        
        # Case 3: morph-only signal inside monologue = expected false positive
        if be['n_detectors'] == 1 and 'morph' in be['detector_types']:
            be['correction_hint'] = 'morph_only_likely_false'
    
    return deduped, speaker_map, line_type_map, line_type_conf_map, morph_boundary_signals, kl_boundary_signals, boundary_evidence


@app.post("/api/entropy_map")
async def entropy_map(req: TensionMapRequest):
    try:
        # Use finditer to capture positions for computing inter-token gaps
        token_pattern = re.compile(r"[\w-]+|[^\w\s]")
        token_matches = list(token_pattern.finditer(req.text))
        tokens = [m.group() for m in token_matches]
        # _gap[i] = whitespace between end of token[i-1] and start of token[i]
        token_gaps = ['']  # first token has no gap
        for j in range(1, len(token_matches)):
            prev_end = token_matches[j - 1].end()
            curr_start = token_matches[j].start()
            token_gaps.append(req.text[prev_end:curr_start])
        if not tokens: return {"status": "success", "data": []}
        kb.prefetch(tokens)
        ner = NEREngine(kb)
        sentiment = SentimentEngine()
        
        identities = {} # lemma -> {canonical, gender, role}
        resolved_entities = []
        
        i = 0
        while i < len(tokens):
            t = tokens[i]
            res = ner.classify_candidate(t)
            
            if res['type'] in ["person", "unknown_capitalized"]:
                l1, gen = kb.get_best_lemma(t)
                parts = [t]; lemmas = [l1]; ni = i + 1
                while ni < len(tokens):
                    nt = tokens[ni]; n_res = ner.classify_candidate(nt)
                    if n_res['type'] == "person" or (nt[0].isupper() and n_res['confidence'] > 0.1):
                        ln, _ = kb.get_best_lemma(nt, gen); parts.append(nt); lemmas.append(ln); ni += 1
                    else: break
                
                full_canonical = " ".join(lemmas)
                social_role = "mention"
                if i > 0 and tokens[i-1].lower() in KINSHIP_MARKERS:
                    social_role = tokens[i-1].lower()
                
                role = "mention"
                if ni < len(tokens) and tokens[ni] == ":": role = "speaker"
                elif ni + 1 < len(tokens) and tokens[ni] == "—": role = "speaker"
                
                id_key = lemmas[-1].lower()
                if id_key not in identities or len(full_canonical) > len(identities[id_key]['canonical']):
                    identities[id_key] = {"canonical": full_canonical, "gender": gen, "role": social_role}
                
                for idx in range(i, ni): 
                    resolved_entities.append({
                        "idx": idx, "type": "person", "role": role, 
                        "social": social_role,
                        "confidence": 1.0 if role=="speaker" else res['confidence'], 
                        "canonical": full_canonical
                    })
                i = ni - 1
            i += 1

        entity_map = {e['idx']: e for e in resolved_entities}
        for i, t in enumerate(tokens):
            if i not in entity_map and t.lower() in identities:
                id_info = identities[t.lower()]
                entity_map[i] = {
                    "idx": i, "type": "person", "role": "mention", 
                    "social": id_info['role'],
                    "confidence": 0.8, "canonical": id_info['canonical']
                }

        results = []
        in_quotes = False
        
        # Service word classification tables (from YAML)
        _discourse_conjunctions = lex.discourse_roles
        _modal_particles = lex.modal_roles
        _prep_semantic_roles = lex.prep_roles
        
        for i, t in enumerate(tokens):
            if t in ['"', '«', '»']: in_quotes = not in_quotes
            ent = entity_map.get(i)
            
            # Entropy Calculation (True H_morph)
            h = 0.5
            if t[0].isalnum():
                h = kb.get_h_morph(t)
            
            # Operator Detection
            op_type = operators.get_type(t)
            
            # === Morphological analysis: POS + lemma + grammemes ===
            tok_pos = ''
            tok_lemma = ''
            tok_grammemes = {}
            tok_service_type = ''    # 'conjunction', 'particle', 'preposition', 'interjection'
            tok_discourse_role = ''  # for conjunctions: 'contrast', 'cause', etc.
            tok_modal_type = ''      # for particles: 'interrogative', 'negation', etc.
            tok_sem_role = ''        # for prepositions: 'direction', 'source', etc.
            
            _pos_overrides = lex.pos_overrides
            
            if t[0:1].isalpha():
                t_lower = t.lower()
                override = _pos_overrides.get(t_lower)
                try:
                    parses = inflector_analyze(t)
                    if override:
                        # Use override POS + lemma, but still get grammemes from parse
                        tok_pos, tok_lemma = override
                        # Try to find matching parse for grammemes
                        p = parses[0] if parses else None
                        for pp in (parses or []):
                            if getattr(pp, 'pos', '') == tok_pos:
                                p = pp
                                break
                    elif parses:
                        p = parses[0]
                        tok_pos = getattr(p, 'pos', '')
                        tok_lemma = getattr(p, 'lemma', t_lower)
                    else:
                        p = None
                        tok_lemma = t_lower
                    
                    if p:
                        tok_grammemes = {
                            k: getattr(p, k, None)
                            for k in ('gender', 'case', 'number', 'tense', 
                                      'aspect', 'mood', 'person', 'voice',
                                      'animacy', 'transitivity')
                            if getattr(p, k, None) is not None
                        }
                except Exception:
                    tok_lemma = t.lower()
                
                # Classify service words (outside try/except so overrides always work)
                if tok_pos == 'PREP':
                    tok_service_type = 'preposition'
                    tok_sem_role = _prep_semantic_roles.get(tok_lemma, '')
                elif tok_pos == 'CONJ':
                    tok_service_type = 'conjunction'
                    tok_discourse_role = _discourse_conjunctions.get(tok_lemma, '')
                elif tok_pos == 'PRCL':
                    tok_service_type = 'particle'
                    tok_modal_type = _modal_particles.get(tok_lemma, '')
                elif tok_pos == 'INTJ':
                    tok_service_type = 'interjection'
            
            tok_dict = {
                "word": t, "clean": ent['canonical'] if ent else t, "h": h,
                "s": sentiment.get_score(t),
                "pos": tok_pos, "lemma": tok_lemma,
                "is_entity": ent is not None, "context_role": ent['role'] if ent else "none",
                "social": ent['social'] if ent else "none",
                "confidence": ent['confidence'] if ent else 0.0,
                "is_dialogue": in_quotes or t in ['—', '-'],
                "is_operator": op_type is not None,
                "op_type": op_type,
                "_gap": token_gaps[i] if i < len(token_gaps) else ""
            }
            # Add grammemes if present
            if tok_grammemes:
                tok_dict['grammemes'] = tok_grammemes
            # Add service word classification if present
            if tok_service_type:
                tok_dict['service_type'] = tok_service_type
            if tok_discourse_role:
                tok_dict['discourse_role'] = tok_discourse_role
            if tok_modal_type:
                tok_dict['modal_type'] = tok_modal_type
            if tok_sem_role:
                tok_dict['sem_role'] = tok_sem_role
                
            results.append(tok_dict)
        # --- Stylometry & Rhythm ---
        stylometry_result = compute_stylometry(req.text)
        # Sentence lengths for rhythm track
        sent_re = re.compile(r'[.!?…]+[\s]+|[.!?…]+$')
        raw_sents = sent_re.split(req.text)
        sentence_lengths = [len(re.findall(r'[а-яёА-ЯЁa-zA-Z]+', s)) for s in raw_sents if s.strip()]

        # --- Plot Arc Analysis (Formal System Σ) ---
        plot_arc = None
        try:
            pr = analyze_plot(req.text)
            tensions = pr.detail.get('tensions', [])
            n = len(tensions)
            climax_idx = max(range(n), key=lambda i: tensions[i]) if n else 0
            # Segment into Freytag zones
            stages = []
            if n > 0:
                for i in range(n):
                    pos = i / max(n - 1, 1)
                    if i < climax_idx:
                        # Pre-climax: exposition vs rising
                        if tensions[i] < 0.2 and i < n * 0.3:
                            stages.append('exposition')
                        else:
                            stages.append('rising_action')
                    elif i == climax_idx:
                        stages.append('climax')
                    else:
                        # Post-climax: falling vs denouement
                        if i > n * 0.85:
                            stages.append('denouement')
                        else:
                            stages.append('falling_action')
            # Diagnostics: detect missing elements
            diagnostics = []
            if pr.arc_closure < 1.0:
                open_count = sum(1 for o, c in pr.detail.get('arcs', []) if c is None) if 'arcs' in pr.detail else 0
                diagnostics.append({'type': 'open_arcs', 'message': f'{open_count} незакрытых арок', 'severity': 'warning'})
            if pr.inevitability < 0.3:
                diagnostics.append({'type': 'no_buildup', 'message': 'Нет нарастания к кульминации', 'severity': 'info'})
            if pr.surprise < 0.1:
                diagnostics.append({'type': 'flat', 'message': 'Плоский сюжет без поворотов', 'severity': 'warning'})
            nrt = pr.detail.get('narrativity', {})
            if nrt.get('is_chronicle'):
                diagnostics.append({'type': 'chronicle', 'message': 'Хроника: последовательность без конфликта', 'severity': 'info'})
            if n > 0 and climax_idx == n - 1 and n > 3:
                diagnostics.append({'type': 'truncated', 'message': 'Текст обрывается на кульминации — нет развязки', 'severity': 'warning'})
            if n > 0 and all(t < 0.3 for t in tensions):
                diagnostics.append({'type': 'no_climax', 'message': 'Кульминация не выражена', 'severity': 'warning'})
            plot_arc = {
                'beauty_score': round(pr.beauty_score, 3),
                'surprise': round(pr.surprise, 3),
                'inevitability': round(pr.inevitability, 3),
                'arc_closure': round(pr.arc_closure, 3),
                'causality': round(pr.causality, 3),
                'n_events': pr.detail.get('n_events', 0),
                'tensions': [round(t, 3) for t in tensions],
                'events': pr.detail.get('event_labels', []),
                'stages': stages,
                'climax_idx': climax_idx,
                'diagnostics': diagnostics,
            }
        except Exception as e:
            print(f'Plot analysis failed: {e}')
            plot_arc = None

        # --- Structural Segmentation ---
        text_segments = []
        speaker_map = {}
        line_type_map = {}
        line_type_conf_map = {}
        morph_boundaries = []
        kl_boundaries = []
        fused_boundaries = {}
        try:
            text_segments, speaker_map, line_type_map, line_type_conf_map, morph_boundaries, kl_boundaries, fused_boundaries = segment_text(req.text, tokens, entity_map)
        except Exception as e:
            print(f'Segmentation failed: {e}')
        
        # Inject speaker/turn/line_type into token results
        for i, r in enumerate(results):
            si = speaker_map.get(i)
            if si:
                r['speaker'] = si['speaker']
                r['turn_id'] = si['turn_id']
                r['speaker_confidence'] = si.get('speaker_confidence', 0.9)
            r['line_type'] = line_type_map.get(i, 'TEXT')
            r['line_type_confidence'] = line_type_conf_map.get(i, 0.5)
        
        # Inherit speaker for orphan STAGE_DIRECTION tokens (e.g., trailing '.' after 'Садятся')
        for i, r in enumerate(results):
            if not r.get('speaker') and r.get('line_type') == 'STAGE_DIRECTION' and i > 0:
                prev = results[i - 1]
                if prev.get('speaker'):
                    r['speaker'] = prev['speaker']
                    r['turn_id'] = prev['turn_id']

        # --- Entity registry + Addressee detection ---
        # Build canonical entity registry from speaker segments
        # Handles: ФАМУСОВ / Фамусов / фамусов → entity_id 'famusov'
        known_speaker_names = set()
        entity_registry = {}  # lowercase_form → {'canonical': str, 'entity_id': str}
        
        for s in text_segments:
            if s['type'] == 'speaker':
                raw_name = s.get('reason', '').replace('form:', '').strip()
                if not raw_name:
                    continue
                known_speaker_names.add(raw_name)
                canonical = raw_name.title() if raw_name.isupper() else raw_name
                eid = canonical.lower().replace('ё', 'е')
                
                # Register all case variants
                for variant in (raw_name, raw_name.lower(), raw_name.upper(), canonical):
                    entity_registry[variant] = {'canonical': canonical, 'entity_id': eid}
                
                # Try inflector for oblique forms (Фамусова → Фамусов)
                try:
                    parses = inflector_analyze(canonical)
                    if parses:
                        lemma = getattr(parses[0], 'lemma', None)
                        if lemma and lemma != canonical.lower():
                            canon_from_lemma = lemma.title()
                            entity_registry[lemma] = {'canonical': canon_from_lemma, 'entity_id': eid}
                            entity_registry[lemma.title()] = {'canonical': canon_from_lemma, 'entity_id': eid}
                except Exception:
                    pass
        
        def resolve_entity(word):
            """Resolve word to (canonical_name, entity_id) or (None, None)."""
            entry = entity_registry.get(word) or entity_registry.get(word.lower())
            if entry:
                return entry['canonical'], entry['entity_id']
            return None, None
        
        # Per-turn: collect addressees and speech_acts
        turn_addressees = {}  # turn_id → set of addressee names
        turn_speech_acts = {}  # turn_id → {act: confidence}
        
        for i, r in enumerate(results):
            tid = r.get('turn_id')
            if tid is None:
                continue
            lt = r.get('line_type', 'TEXT')
            
            # Addressee: entity in TEXT that matches a known speaker,
            # or word that directly matches a known speaker name
            is_entity_match = r.get('is_entity') and r.get('confidence', 0) >= 0.6
            is_speaker_name_match = r['word'] in known_speaker_names
            if lt == 'TEXT' and (is_entity_match or is_speaker_name_match):
                canon = r.get('clean', '')
                # Check if this entity matches any known speaker
                matched_speaker = None
                for sn in known_speaker_names:
                    if canon.lower() == sn.lower() or r['word'].lower() == sn.lower():
                        matched_speaker = sn
                        break
                if matched_speaker and matched_speaker != r.get('speaker', ''):
                    # Vocative check: preceded or followed by comma, exclamation
                    prev_word = results[i-1]['word'] if i > 0 else ''
                    next_word = results[i+1]['word'] if i+1 < len(results) else ''
                    is_vocative = prev_word in ',!;—' or next_word in ',!?;'
                    if is_vocative:
                        r['is_addressee'] = True
                        r['addressee_of'] = r.get('speaker', '')
                        if tid not in turn_addressees:
                            turn_addressees[tid] = set()
                        turn_addressees[tid].add(matched_speaker)
            
            # Speech act detection: punctuation + morphological signals
            if r['word'] == '?' and lt == 'TEXT':
                if tid not in turn_speech_acts:
                    turn_speech_acts[tid] = {}
                turn_speech_acts[tid]['question'] = 1.0
                
                # Rhetorical question detection via 3 signals:
                # Signal 1: rhetorical markers in the question clause
                rhetorical_markers = lex.rhetorical_markers
                has_marker = False
                # Scan backwards from '?' to previous sentence end or turn start
                for back_j in range(i - 1, max(i - 30, -1), -1):
                    bw = results[back_j]['word'].lower()
                    if bw in ('.', '!', '?', '…'):
                        break
                    if bw in rhetorical_markers:
                        has_marker = True
                        break
                    # Also check lemmas
                    try:
                        bp = inflector_analyze(bw)
                        if bp and getattr(bp[0], 'lemma', '') in rhetorical_markers:
                            has_marker = True
                            break
                    except Exception:
                        pass
                
                if has_marker:
                    turn_speech_acts[tid]['rhetorical_question'] = 0.90
                else:
                    # Signal 2: question followed by statement in same turn
                    # (self-response pattern: "Что мне делать? Пойти домой.")
                    has_self_response = False
                    for fwd_j in range(i + 1, min(i + 30, len(results))):
                        fw = results[fwd_j]
                        if fw.get('turn_id') != tid:
                            break
                        if fw['word'] in ('.', '…') and fw.get('line_type') == 'TEXT':
                            # Found a declarative sentence after the question
                            has_self_response = True
                            break
                        if fw['word'] == '?':
                            break  # another question, not self-response
                    
                    if has_self_response:
                        turn_speech_acts[tid]['rhetorical_question'] = 0.65
                
            elif r['word'] == '!' and lt == 'TEXT':
                if tid not in turn_speech_acts:
                    turn_speech_acts[tid] = {}
                turn_speech_acts[tid]['exclamation'] = 1.0
            
            # Negation at start of turn: "Нет, ..." → denial
            if lt == 'TEXT' and r['word'].lower() in ('нет', 'никак', 'нельзя') and i > 0:
                prev_lt = results[i-1].get('line_type', '')
                if prev_lt == 'SPEAKER' or (i > 1 and results[i-2].get('line_type') == 'SPEAKER'):
                    if tid not in turn_speech_acts:
                        turn_speech_acts[tid] = {}
                    turn_speech_acts[tid]['denial'] = 0.75
            
            # Imperative mood → command (with particle normalization)
            if lt == 'TEXT' and r['word'][0].isalpha():
                try:
                    # Strip softening particles: -ка, -ко, -то, -нибудь, -таки
                    word_norm = r['word']
                    for particle in ('-ка', '-ко', '-то', '-нибудь', '-таки', '-с'):
                        if word_norm.lower().endswith(particle):
                            word_norm = word_norm[:len(word_norm) - len(particle)]
                            break
                    
                    parses = inflector_analyze(word_norm)
                    if parses and getattr(parses[0], 'mood', None) == 'impr' and getattr(parses[0], 'pos', None) == 'VERB':
                        if tid not in turn_speech_acts:
                            turn_speech_acts[tid] = {}
                        if 'command' not in turn_speech_acts[tid]:
                            turn_speech_acts[tid]['command'] = 0.80
                except Exception:
                    pass
        
        # Inject addressee, speech_act, entity_role, and entity_id into turn tokens
        for i, r in enumerate(results):
            tid = r.get('turn_id')
            if tid is not None:
                if tid in turn_addressees:
                    r['turn_addressees'] = list(turn_addressees[tid])
                if tid in turn_speech_acts:
                    r['speech_acts'] = turn_speech_acts[tid]  # dict {act: confidence}
                # Normalize speaker name via entity registry
                spk = r.get('speaker', '')
                canon, eid = resolve_entity(spk)
                if eid:
                    r['speaker'] = canon  # normalize speaker name
                    r['entity_id'] = eid
            
            # Entity/Role assignment (F.88-90) + entity_id
            lt = r.get('line_type', '')
            if lt == 'SPEAKER':
                r['entity_role'] = 'speaker'
                canon, eid = resolve_entity(r['word'])
                if eid:
                    r['entity_id'] = eid
            elif r.get('is_addressee'):
                r['entity_role'] = 'addressee'
                canon, eid = resolve_entity(r['word'])
                if eid:
                    r['entity_id'] = eid
            elif lt == 'TEXT' and r.get('is_entity') and r.get('confidence', 0) >= 0.6:
                r['entity_role'] = 'mentioned'
                canon, eid = resolve_entity(r['word'])
                if eid:
                    r['entity_id'] = eid
        
        # --- Turn-pair linking ---
        # Link question turns to their answers: turn N (?) → turn N+1
        turn_pairs = []  # [{question_turn, answer_turn, type}]
        # Build turn_id → info map
        turn_info = {}  # turn_id → {speaker, start_tok, end_tok, speech_acts}
        for i, r in enumerate(results):
            tid = r.get('turn_id')
            if tid is None:
                continue
            if tid not in turn_info:
                turn_info[tid] = {
                    'speaker': r.get('speaker', ''),
                    'start_tok': i,
                    'end_tok': i,
                    'speech_acts': r.get('speech_acts', {}),
                }
            else:
                turn_info[tid]['end_tok'] = i
                if r.get('speech_acts'):
                    turn_info[tid]['speech_acts'].update(r['speech_acts'])
        
        sorted_turns = sorted(turn_info.keys())
        for j in range(len(sorted_turns) - 1):
            t_curr = sorted_turns[j]
            t_next = sorted_turns[j + 1]
            curr_acts = turn_info[t_curr].get('speech_acts', {})
            next_acts = turn_info[t_next].get('speech_acts', {})
            
            # Question → Answer
            if 'question' in curr_acts:
                pair_type = 'question_answer'
                if 'denial' in next_acts:
                    pair_type = 'question_denial'
                turn_pairs.append({
                    'source_turn': t_curr,
                    'target_turn': t_next,
                    'type': pair_type,
                    'source_speaker': turn_info[t_curr]['speaker'],
                    'target_speaker': turn_info[t_next]['speaker'],
                })
            # Command → Response
            elif 'command' in curr_acts:
                turn_pairs.append({
                    'source_turn': t_curr,
                    'target_turn': t_next,
                    'type': 'command_response',
                    'source_speaker': turn_info[t_curr]['speaker'],
                    'target_speaker': turn_info[t_next]['speaker'],
                })
            # Exclamation → Reaction (weaker link)
            elif 'exclamation' in curr_acts and turn_info[t_curr]['speaker'] != turn_info[t_next]['speaker']:
                turn_pairs.append({
                    'source_turn': t_curr,
                    'target_turn': t_next,
                    'type': 'exclamation_reaction',
                    'source_speaker': turn_info[t_curr]['speaker'],
                    'target_speaker': turn_info[t_next]['speaker'],
                })
        
        # --- Cross-turn pronoun coreference ---
        # ты/вы → last detected addressee for this speaker
        speaker_last_addressee = {}  # speaker_name → addressee_name
        for tp in turn_pairs:
            speaker_last_addressee[tp['source_speaker']] = tp['target_speaker']
            speaker_last_addressee[tp['target_speaker']] = tp['source_speaker']
        
        # Also from vocative addressees
        for tid, addrs in turn_addressees.items():
            if tid in turn_info:
                spk = turn_info[tid]['speaker']
                for addr in addrs:
                    speaker_last_addressee[spk] = addr
        
        # Inject resolved pronouns
        for i, r in enumerate(results):
            if r.get('line_type') != 'TEXT':
                continue
            word_lower = r['word'].lower()
            spk = r.get('speaker', '')
            if word_lower in ('ты', 'тебя', 'тебе', 'тобой', 'тобою', 'вы', 'вас', 'вам', 'вами'):
                resolved = speaker_last_addressee.get(spk)
                if resolved:
                    r['pronoun_ref'] = resolved
                    r['pronoun_type'] = '2per'
            
            # 3rd person pronouns → last mentioned entity of matching gender
            elif word_lower in ('он', 'его', 'ему', 'им', 'нём', 'него'):
                # Find last mentioned masc entity before this position
                ref = _find_last_entity_by_gender(results, i, 'masc', known_speaker_names, spk)
                if ref:
                    r['pronoun_ref'] = ref
                    r['pronoun_type'] = '3per_masc'
            elif word_lower in ('она', 'её', 'ей', 'ею', 'ней', 'неё'):
                ref = _find_last_entity_by_gender(results, i, 'fem', known_speaker_names, spk)
                if ref:
                    r['pronoun_ref'] = ref
                    r['pronoun_type'] = '3per_fem'
        
        # --- Build dialogue_turns[] ---
        dialogue_turns = []
        for tid in sorted_turns:
            ti = turn_info[tid]
            # Collect TEXT-only words for utterance_content
            text_words = []
            for idx in range(ti['start_tok'], ti['end_tok'] + 1):
                if idx < len(results):
                    tok_r = results[idx]
                    if tok_r.get('line_type') in ('TEXT',):
                        text_words.append(tok_r['word'])
            
            dt = {
                'turn_id': tid,
                'speaker': ti['speaker'],
                'start_token': ti['start_tok'],
                'end_token': ti['end_tok'],
                'text': ' '.join(text_words),
                'speech_acts': ti['speech_acts'],
            }
            # Add entity_id for speaker
            canon, eid = resolve_entity(ti['speaker'])
            if eid:
                dt['speaker'] = canon
                dt['entity_id'] = eid
            if tid in turn_addressees:
                dt['addressees'] = list(turn_addressees[tid])
            
            # Internal segments: split by line_type transitions within the turn
            segments_internal = []
            curr_seg_type = None
            curr_seg_words = []
            curr_seg_start = None
            current_quote_subtype = 'embedded_quote'
            in_quote = False
            for idx in range(ti['start_tok'], ti['end_tok'] + 1):
                if idx >= len(results):
                    break
                tok_r = results[idx]
                tok_lt = tok_r.get('line_type', 'TEXT')
                
                # Track embedded quotes: «...»
                if tok_r['word'] == '«':
                    in_quote = True
                    # Sub-classify the quote by preceding context
                    # Look back up to 3 tokens for classification signals
                    quote_subtype = 'embedded_quote'  # default
                    prev_words = []
                    for back in range(1, min(4, idx + 1)):
                        pw = results[idx - back]['word'].lower() if idx - back >= 0 else ''
                        if pw == ':':  # skip colon (сказал: «...»)
                            continue
                        prev_words.append(pw)
                    prev_lemmas = set()
                    for pw in prev_words:
                        if pw:
                            try:
                                parses = inflector_analyze(pw)
                                for p in parses:
                                    prev_lemmas.add(getattr(p, 'lemma', pw))
                            except Exception:
                                prev_lemmas.add(pw)
                    
                    # Title: preceded by work-type nouns
                    if prev_lemmas & lex.title_signals:
                        quote_subtype = 'title'
                    # Embedded speech: preceded by speech verbs
                    elif prev_lemmas & lex.speech_verbs:
                        quote_subtype = 'embedded_speech'
                    # Ironic: preceded by meta-markers
                    elif any(w in prev_words for w in lex.ironic_markers):
                        quote_subtype = 'ironic'
                    
                    current_quote_subtype = quote_subtype
                elif tok_r['word'] == '»':
                    in_quote = False
                
                # Map to segment type
                seg_type = 'dialogue'
                if tok_lt == 'STAGE_DIRECTION':
                    seg_type = 'stage_direction'
                elif tok_lt == 'SPEAKER':
                    seg_type = 'speaker_label'
                elif in_quote and tok_lt == 'TEXT':
                    seg_type = current_quote_subtype
                
                if seg_type != curr_seg_type:
                    if curr_seg_type and curr_seg_words:
                        segments_internal.append({
                            'type': curr_seg_type,
                            'text': ' '.join(curr_seg_words),
                            'start_token': curr_seg_start,
                            'end_token': idx - 1,
                        })
                    curr_seg_type = seg_type
                    curr_seg_words = [tok_r['word']]
                    curr_seg_start = idx
                else:
                    curr_seg_words.append(tok_r['word'])
            
            if curr_seg_type and curr_seg_words:
                segments_internal.append({
                    'type': curr_seg_type,
                    'text': ' '.join(curr_seg_words),
                    'start_token': curr_seg_start,
                    'end_token': ti['end_tok'],
                })
            
            dt['segments'] = segments_internal
            dialogue_turns.append(dt)
        
        # --- Build text_blocks[] ---
        text_blocks = []
        for seg in text_segments:
            block = {
                'type': seg['type'],  # heading, speaker, stage_direction, characters_line
                'after_token': seg['after_token'],
                'confidence': seg.get('confidence', 0.0),
            }
            if seg.get('reason'):
                block['label'] = seg['reason'].replace('form:', '').strip()
            text_blocks.append(block)

        # Detect dialogue format for routing
        dialogue_format = 'unknown'
        try:
            _dp_dir = str(Path(__file__).parent)
            if _dp_dir not in sys.path:
                sys.path.insert(0, _dp_dir)
            from dialogue_parser import detect_format as dp_detect_format
            dialogue_format = dp_detect_format(req.text).value
        except Exception:
            pass
        
        # Compute depth metrics
        depth = compute_depth_metrics(results)
        
        # === Aggregate service word statistics ===
        n_content = 0
        n_service = 0
        discourse_profile = {}  # contrast: N, cause: N, ...
        modal_profile = {}      # interrogative: N, negation: N, ...
        pos_distribution = {}   # NOUN: N, VERB: N, PREP: N, ...
        
        for tok in results:
            pos = tok.get('pos', '')
            if pos:
                pos_distribution[pos] = pos_distribution.get(pos, 0) + 1
            
            st = tok.get('service_type', '')
            if st:
                n_service += 1
            elif tok['word'].isalpha():
                n_content += 1
            
            dr = tok.get('discourse_role', '')
            if dr:
                discourse_profile[dr] = discourse_profile.get(dr, 0) + 1
            mt = tok.get('modal_type', '')
            if mt:
                modal_profile[mt] = modal_profile.get(mt, 0) + 1
        
        total_words = n_content + n_service
        service_word_stats = {
            'n_content': n_content,
            'n_service': n_service,
            'lexical_density': round(n_content / total_words, 3) if total_words > 0 else 0,
            'discourse_profile': discourse_profile,
            'modal_profile': modal_profile,
            'pos_distribution': pos_distribution,
        }
        
        return {
            "schema_version": 6,
            "status": "success",
            "data": results,
            "stylometry": stylometry_result.to_dict(),
            "depth": depth,
            "service_word_stats": service_word_stats,
            "rhythm": sentence_lengths,
            "genre": detect_genre(req.text),
            "dialogue_format": dialogue_format,
            "plot_arc": plot_arc,
            "segments": text_segments,
            "morph_boundaries": morph_boundaries,
            "kl_boundaries": kl_boundaries,
            "boundary_evidence": list(fused_boundaries.values()),
            "turn_pairs": turn_pairs,
            "dialogue_turns": dialogue_turns,
            "text_blocks": text_blocks,
        }
    except Exception:
        print(traceback.format_exc()); raise HTTPException(status_code=500, detail="Error")

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.endswith(('.html', '.js', '.css')):
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

app.add_middleware(NoCacheMiddleware)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
