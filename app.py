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

STOP_WORDS = {"и", "а", "но", "в", "на", "с", "из", "по", "к", "о", "у", "я", "он", "она", "они", "мы", "вы", "тот", "это", "как", "так", "что", "когда", "если", "был", "была", "было", "были", "уже", "еще", "всё", "все"}
TITLES = {"сударь", "сударыня", "милостивый", "господин", "госпожа", "князь", "граф", "барин", "барышня"}
KINSHIP_MARKERS = {
    "дочь", "сын", "отец", "мать", "брат", "сестра", "дядя", "тетя", 
    "племянник", "племянница", "внук", "внучка", "жена", "муж", 
    "слуга", "служанка", "горничная", "друг", "подруга", "хозяйка", "хозяин"
}

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
        self.pos = {"радость", "любовь", "счастье", "милый", "добрый", "хорошо", "смех", "надежда", "друг"}
        self.neg = {"грусть", "смерть", "боль", "злой", "плохо", "враг", "тоска", "ужас", "страх", "отказ"}

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
            return ('stage_direction', 0)
        # Standalone closing paren from multi-line stage direction
        if s == ')':
            return ('stage_direction', 0)
        
        # Below this: only short lines (≤80 chars, ≤8 words)
        if len(s) > 80:
            return (None, 0)
        words = re.findall(r'[\w]+', s)
        if not words or len(words) > 8:
            return (None, 0)
        
        # ── Speaker with colon: "ФАМУСОВ:" or "Charles:" ──
        if s.endswith(':') and len(words) <= 3:
            return ('speaker', 2)
        
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
            _STAGE_NOUNS = {
                'молчание', 'пауза', 'занавес', 'антракт', 'темнота',
                'тишина', 'аплодисменты',
            }
            lower_set = {w.lower().rstrip('.') for w in words}
            if is_stage_verb or (lower_set & _STAGE_NOUNS):
                return ('stage_direction', 0)
        
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
            return ('speaker', 2)
        
        # Single Title Case word = speaker (Чацкий, Sofia, Молчалин)
        # Next line must exist and be either text or stage direction
        if (len(words) == 1 and not all_caps and not has_numeral 
                and not ends_with_punct and not has_bad_punct
                and words[0][0].isupper()
                and next_line
                and (next_line.startswith('(') or len(next_line.split()) > 1 or next_line != next_line.strip().title())):
            return ('speaker', 2)
        
        # Must be preceded by blank line for remaining structural markers
        # (headings, characters_line — these require more context)
        if not prev_blank:
            return (None, 0)
        
        # ── Characters line: names with connectives ──
        # "Лиза и Фамусов", "София, Лиза и Молчалин", "Romeo and Juliet"
        cap_words = [w for w in alpha_words if w[0].isupper()]
        lower_words = [w for w in words if w[0].islower()]
        if (len(cap_words) >= 2 and not ends_with_punct and not has_numeral 
                and 2 <= len(alpha_words) <= 6 and not all_caps
                and lower_words):
            return ('characters_line', 2)
        
        # ── Multi-word CAPS or CAPS+numeral = structural heading ──
        if all_caps and (len(words) >= 2 or has_numeral) and not ends_with_punct:
            return ('heading', 3)
        
        # ── Title Case + numeral = structural heading (Chapter 3, Явление 10) ──
        # Single capitalized word + numeral counts (not just multi-word Title Case)
        if has_numeral and not ends_with_punct and alpha_words and all(w[0].isupper() for w in alpha_words):
            return ('heading', 3)
        
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
    prev_blank = True  # start of text counts as preceded by blank
    for li, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            prev_blank = True
            continue
        
        next_line = lines[li + 1].strip() if li + 1 < len(lines) else ''
        ltype, llevel = _classify_line(stripped, prev_blank, next_line)
        
        line_tok_count = len(re.findall(r'[\w-]+|[^\w\s]', stripped))
        
        # Map line_type for all tokens on this line
        lt = 'TEXT'
        if ltype == 'heading':
            lt = 'HEADER'
        elif ltype == 'speaker':
            lt = 'SPEAKER'
        elif ltype == 'stage_direction':
            lt = 'STAGE_DIRECTION'
        elif ltype == 'characters_line':
            lt = 'CHARACTERS_LINE'
        
        for ti in range(line_start_token, line_start_token + line_tok_count):
            if ti < len(tokens):
                line_type_map[ti] = lt
        
        # Detect inline stage directions: tokens inside () within TEXT lines
        if lt == 'TEXT':
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
                            'level': llevel,
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
    
    # Sort by position, deduplicate (keep highest level)
    segments.sort(key=lambda s: (s['after_token'], -s['level']))
    
    # Deduplicate: at same position, keep highest level
    deduped = []
    seen_positions = set()
    for s in segments:
        if s['after_token'] not in seen_positions:
            deduped.append(s)
            seen_positions.add(s['after_token'])
    
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
            
            # Mark the speaker name token
            speaker_map[speaker_tok] = {'speaker': speaker_name, 'turn_id': turn_id, 'is_speaker_label': True}
            # Mark all tokens in this turn (skip HEADER tokens, start after speaker token)
            for ti in range(speaker_tok + 1, end_tok):
                if line_type_map.get(ti) != 'HEADER':
                    speaker_map[ti] = {'speaker': speaker_name, 'turn_id': turn_id, 'is_speaker_label': False}
            
            turn_id += 1
    
    return deduped, speaker_map, line_type_map


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
        for i, t in enumerate(tokens):
            if t in ['"', '«', '»']: in_quotes = not in_quotes
            ent = entity_map.get(i)
            
            # Entropy Calculation (True H_morph)
            h = 0.5
            if t[0].isalnum():
                h = kb.get_h_morph(t)
            
            # Operator Detection
            op_type = operators.get_type(t)
            
            results.append({
                "word": t, "clean": ent['canonical'] if ent else t, "h": h,
                "s": sentiment.get_score(t),
                "is_entity": ent is not None, "context_role": ent['role'] if ent else "none",
                "social": ent['social'] if ent else "none",
                "confidence": ent['confidence'] if ent else 0.0,
                "is_dialogue": in_quotes or t in ['—', '-'],
                "is_operator": op_type is not None,
                "op_type": op_type,
                "_gap": token_gaps[i] if i < len(token_gaps) else ""
            })
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
        try:
            text_segments, speaker_map, line_type_map = segment_text(req.text, tokens, entity_map)
        except Exception as e:
            print(f'Segmentation failed: {e}')
        
        # Inject speaker/turn/line_type into token results
        for i, r in enumerate(results):
            si = speaker_map.get(i)
            if si:
                r['speaker'] = si['speaker']
                r['turn_id'] = si['turn_id']
            r['line_type'] = line_type_map.get(i, 'TEXT')
        
        # Inherit speaker for orphan STAGE_DIRECTION tokens (e.g., trailing '.' after 'Садятся')
        for i, r in enumerate(results):
            if not r.get('speaker') and r.get('line_type') == 'STAGE_DIRECTION' and i > 0:
                prev = results[i - 1]
                if prev.get('speaker'):
                    r['speaker'] = prev['speaker']
                    r['turn_id'] = prev['turn_id']

        # --- Addressee detection ---
        # Find speaker names mentioned inside TEXT lines (vocative/address)
        # Pattern: name entity in TEXT position + comma/exclamation context
        known_speaker_names = set()
        for s in text_segments:
            if s['type'] == 'speaker':
                known_speaker_names.add(s.get('reason', '').replace('form:', '').strip())
        
        # Per-turn: collect addressees and speech_acts
        turn_addressees = {}  # turn_id → set of addressee names
        turn_speech_acts = {}  # turn_id → set of acts
        
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
            
            # Speech act detection: punctuation at end of sentence
            if r['word'] == '?' and lt == 'TEXT':
                if tid not in turn_speech_acts:
                    turn_speech_acts[tid] = set()
                turn_speech_acts[tid].add('question')
            elif r['word'] == '!' and lt == 'TEXT':
                if tid not in turn_speech_acts:
                    turn_speech_acts[tid] = set()
                turn_speech_acts[tid].add('exclamation')
        
        # Inject addressee and speech_act into turn tokens
        for i, r in enumerate(results):
            tid = r.get('turn_id')
            if tid is not None:
                if tid in turn_addressees:
                    r['turn_addressees'] = list(turn_addressees[tid])
                if tid in turn_speech_acts:
                    r['speech_acts'] = list(turn_speech_acts[tid])

        return {
            "status": "success",
            "data": results,
            "stylometry": stylometry_result.to_dict(),
            "rhythm": sentence_lengths,
            "genre": detect_genre(req.text),
            "plot_arc": plot_arc,
            "segments": text_segments,
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
