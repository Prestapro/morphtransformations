#!/usr/bin/env python3
"""Build word_morphemes with BOTH Tikhonov AND algorithmic coverage in one pass.

1. Decompose all OpenCorpora lemmas via Tikhonov
2. For uncovered: try algorithmic decomposition using known morpheme inventory
3. Write everything in one batch

No incremental DELETE — just DROP+CREATE+INSERT.
"""

import json
import os
import sqlite3
import time

_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
DB_PATH = os.path.join(_ROOT, 'data', 'language', 'ru_paradigms.sqlite3')
TIKHONOV_PATH = os.path.join(_ROOT, 'data', 'tikhonov_morphemes.json')
WIKT_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'wiktionary_morphemes.json')

INTERFIXES = {'о', 'е'}

import re
_CLEAN_RE = re.compile(r'^[а-яёА-ЯЁ]+$')
def _is_clean(s):
    """Only Cyrillic letters are valid morphemes (no digits, punctuation, hyphens)."""
    return bool(s) and bool(_CLEAN_RE.match(s))


def load_wikt_suffixes():
    if not os.path.exists(WIKT_PATH):
        return set()
    with open(WIKT_PATH, 'r', encoding='utf-8') as f:
        wikt = json.load(f)
    return {m.lstrip('-').lower().strip() for m in wikt.get('suffixes', []) if m.lstrip('-').lower().strip()}


def classify_tikhonov(entry, wikt_suffixes):
    """Tikhonov entry → ordered [(morpheme, type), ...]"""
    morphemes_raw = entry.get('morphemes', [])
    prefixes = [p.lower().strip() for p in entry.get('prefixes', []) if _is_clean(p.lower().strip())]
    root = entry.get('root', '').lower().strip()
    ending = entry.get('ending', '').lower().strip()
    
    if not morphemes_raw:
        return []
    
    result = []
    prefix_set = set(prefixes)
    suffix_consumed = [s.lower().strip() for s in entry.get('suffixes', []) if _is_clean(s.lower().strip())]
    root_found = False
    
    for i, m_raw in enumerate(morphemes_raw):
        m = m_raw.lower().strip()
        if not m or not _is_clean(m):
            continue
        
        if m == ending and i == len(morphemes_raw) - 1:
            result.append((m, 'ENDING'))
        elif m in prefix_set:
            result.append((m, 'PREFIX'))
            prefix_set.discard(m)
        elif m == root and not root_found:
            result.append((m, 'ROOT'))
            root_found = True
        elif m in suffix_consumed:
            suffix_consumed.remove(m)
            if m in INTERFIXES and root_found:
                result.append((m, 'LINK'))
            elif m in wikt_suffixes:
                result.append((m, 'SUFFIX'))
            elif len(m) >= 3 and m not in wikt_suffixes:
                result.append((m, 'ROOT'))
            else:
                result.append((m, 'SUFFIX'))
        else:
            result.append((m, 'SUFFIX'))
    
    return result


def try_algorithmic(w, prefix_set, root_set, suffix_set, ending_set, max_pfx, max_sfx, max_end):
    """Try to decompose word using known morpheme inventory.
    
    Scoring: prefer longest root, then fewest suffix parts, then known endings.
    """
    if len(w) < 2:
        return None
    
    best = None
    best_score = (-1, -1, -1)  # (root_len, -num_suffixes, has_ending)
    
    def _score(parts):
        root_len = sum(len(v) for v, t in parts if t == 'ROOT')
        n_suf = sum(1 for _, t in parts if t == 'SUFFIX')
        has_end = any(t == 'ENDING' for _, t in parts)
        return (root_len, -n_suf, int(has_end))
    
    def _try_body(pfx, body, end_val):
        """Try to split body into root + optional suffixes."""
        nonlocal best, best_score
        
        base_parts = []
        if pfx: base_parts.append((pfx, 'PREFIX'))
        tail_parts = []
        if end_val: tail_parts.append((end_val, 'ENDING'))
        
        # Direct root match (no suffixes)
        if body in root_set:
            parts = base_parts + [(body, 'ROOT')] + tail_parts
            sc = _score(parts)
            if sc > best_score:
                best_score = sc
                best = parts
        
        # Try 1-3 suffixes from the end
        _try_suffixes(body, base_parts, tail_parts, [], 0)
        
        # Compound: root + link + root (+ optional suffix)
        for i in range(2, len(body) - 1):
            r1 = body[:i]
            if r1 not in root_set:
                continue
            rest = body[i:]
            if not rest or rest[0] not in INTERFIXES or len(rest) < 3:
                continue
            link = rest[0]
            r2_body = rest[1:]
            
            cpd_base = base_parts + [(r1, 'ROOT'), (link, 'LINK')]
            
            if r2_body in root_set:
                parts = cpd_base + [(r2_body, 'ROOT')] + tail_parts
                sc = _score(parts)
                if sc > best_score:
                    best_score = sc
                    best = parts
            
            _try_suffixes(r2_body, cpd_base, tail_parts, [], 0)
    
    def _try_suffixes(body, base_parts, tail_parts, suf_stack, depth):
        """Recursively try 1-3 suffixes from the end of body."""
        nonlocal best, best_score
        if depth >= 3 or len(body) < 1:
            return
        
        for slen in range(1, min(max_sfx + 1, len(body))):
            suf = body[-slen:]
            if suf not in suffix_set:
                continue
            rem = body[:-slen]
            if not rem:
                continue
            
            new_suf_stack = [(suf, 'SUFFIX')] + suf_stack
            
            if rem in root_set:
                parts = base_parts + [(rem, 'ROOT')] + new_suf_stack + tail_parts
                sc = _score(parts)
                if sc > best_score:
                    best_score = sc
                    best = parts
            
            # Try deeper suffix nesting
            _try_suffixes(rem, base_parts, tail_parts, new_suf_stack, depth + 1)
    
    # Try all prefix × ending combinations
    pfx_options = [(None, w)]
    for plen in range(1, min(max_pfx + 1, len(w))):
        if w[:plen] in prefix_set:
            pfx_options.append((w[:plen], w[plen:]))
    
    for pfx, after_pfx in pfx_options:
        if len(after_pfx) < 1:
            continue
        
        # No ending
        _try_body(pfx, after_pfx, None)
        
        # With ending
        for elen in range(1, min(max_end + 1, len(after_pfx))):
            end_cand = after_pfx[-elen:]
            if end_cand in ending_set:
                body = after_pfx[:-elen]
                if body:
                    _try_body(pfx, body, end_cand)
    
    return best


def main():
    t0 = time.time()
    
    # Load Tikhonov
    print("Loading Tikhonov...", flush=True)
    with open(TIKHONOV_PATH, 'r', encoding='utf-8') as f:
        tikh = json.load(f)
    dictionary = tikh.get('dictionary', {})
    wikt_suffixes = load_wikt_suffixes()
    print(f"  {len(dictionary)} entries, {len(wikt_suffixes)} validated suffixes", flush=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get all lemma+pos
    c.execute("SELECT DISTINCT lemma, pos FROM paradigms")
    lemma_pos = c.fetchall()
    print(f"  {len(lemma_pos)} lemma+pos pairs", flush=True)
    
    # Phase 1: Tikhonov decomposition
    print("Phase 1: Tikhonov decomposition...", flush=True)
    all_rows = []
    covered_tikh = 0
    uncovered_lemmas = []
    
    # Collect known morphemes from Tikhonov for phase 2
    known_prefixes = set()
    known_roots = set()
    known_suffixes = set()
    known_endings = set()
    
    # Build ё restoration map: key (без ё) → restored key (с ё)
    yo_map = {}
    for key, entry in dictionary.items():
        morphemes = [m.lower().strip() for m in entry.get('morphemes', []) if m.strip()]
        joined = ''.join(morphemes)
        if 'ё' not in joined or 'ё' in key:
            continue
        # Restore ё by replacing е→ё at the correct positions
        restored = list(key.lower())
        j_pos = 0
        for ch_j in joined:
            if j_pos >= len(restored):
                break
            if ch_j == 'ё' and restored[j_pos] == 'е':
                restored[j_pos] = 'ё'
            j_pos += 1
        yo_map[key] = ''.join(restored)
    print(f"  ё restoration: {len(yo_map)} words", flush=True)
    
    for lemma, pos in lemma_pos:
        lkey = lemma.lower().strip()
        # Normalize ё→е for Tikhonov lookup (Tikhonov keys don't use ё)
        lkey_norm = lkey.replace('ё', 'е')
        entry = dictionary.get(lkey_norm) or dictionary.get(lkey) or dictionary.get(lemma)
        if entry:
            morphemes = classify_tikhonov(entry, wikt_suffixes)
            # Use lemma with ё: prefer original if it has ё, else restore from yo_map
            display_lemma = lemma if 'ё' in lemma else yo_map.get(lkey_norm, lemma)
            for pos_idx, (morph, mtype) in enumerate(morphemes):
                all_rows.append((display_lemma, pos, morph, mtype, pos_idx, 'tikhonov'))
                if mtype == 'PREFIX': known_prefixes.add(morph)
                elif mtype == 'ROOT': known_roots.add(morph)
                elif mtype == 'SUFFIX': known_suffixes.add(morph)
                elif mtype == 'ENDING': known_endings.add(morph)
            covered_tikh += 1
        else:
            uncovered_lemmas.append((lemma, pos))
    
    print(f"  Tikhonov: {covered_tikh} covered, {len(uncovered_lemmas)} uncovered", flush=True)
    print(f"  Inventory: P={len(known_prefixes)} R={len(known_roots)} S={len(known_suffixes)} E={len(known_endings)}", flush=True)
    
    # Phase 2: Algorithmic decomposition
    print("Phase 2: Algorithmic decomposition...", flush=True)
    max_pfx = max((len(p) for p in known_prefixes), default=0)
    max_sfx = max((len(s) for s in known_suffixes), default=0)
    max_end = max((len(e) for e in known_endings), default=0)
    
    covered_algo = 0
    still_unknown = 0
    
    for i, (lemma, pos) in enumerate(uncovered_lemmas):
        lclean = lemma.lower().strip()
        # Skip lemmas with non-Cyrillic characters (digits, dots, apostrophes)
        if not _is_clean(lclean):
            still_unknown += 1
            if (i + 1) % 10000 == 0:
                print(f"  {i+1}/{len(uncovered_lemmas)}  +{covered_algo} algo, {still_unknown} unknown", flush=True)
            continue
        result = try_algorithmic(
            lclean,
            known_prefixes, known_roots, known_suffixes, known_endings,
            max_pfx, max_sfx, max_end
        )
        if result:
            for pos_idx, (morph, mtype) in enumerate(result):
                all_rows.append((lemma, pos, morph, mtype, pos_idx, 'algorithmic'))
            covered_algo += 1
        else:
            all_rows.append((lemma, pos, lclean, 'ROOT', 0, 'unknown'))
            still_unknown += 1
        
        if (i + 1) % 10000 == 0:
            print(f"  {i+1}/{len(uncovered_lemmas)}  +{covered_algo} algo, {still_unknown} unknown", flush=True)
    
    print(f"  Algorithmic: +{covered_algo}, Still unknown: {still_unknown}", flush=True)
    
    # Phase 3: Write to DB in one shot
    print(f"Writing {len(all_rows)} rows...", flush=True)
    c.execute("DROP TABLE IF EXISTS word_morphemes")
    c.execute("""
        CREATE TABLE word_morphemes (
            lemma TEXT NOT NULL,
            pos TEXT NOT NULL,
            morpheme TEXT NOT NULL,
            mtype TEXT NOT NULL,
            position INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'tikhonov'
        )
    """)
    c.executemany(
        "INSERT INTO word_morphemes (lemma, pos, morpheme, mtype, position, source) VALUES (?, ?, ?, ?, ?, ?)",
        all_rows
    )
    
    print("Creating indexes...", flush=True)
    c.execute("CREATE INDEX idx_wm_lemma ON word_morphemes(lemma)")
    c.execute("CREATE INDEX idx_wm_morpheme ON word_morphemes(morpheme)")
    c.execute("CREATE INDEX idx_wm_mtype ON word_morphemes(mtype)")
    c.execute("CREATE INDEX idx_wm_source ON word_morphemes(source)")
    c.execute("CREATE INDEX idx_wm_mtype_morpheme ON word_morphemes(mtype, morpheme)")
    
    conn.commit()
    
    # Stats
    c.execute("SELECT source, COUNT(DISTINCT lemma) FROM word_morphemes GROUP BY source")
    print("\nFinal coverage:")
    for src, cnt in c.fetchall():
        print(f"  {src}: {cnt}")
    
    c.execute("SELECT mtype, COUNT(DISTINCT morpheme) FROM word_morphemes WHERE source != 'unknown' GROUP BY mtype")
    print("\nUnique morphemes (covered):")
    for mtype, cnt in c.fetchall():
        print(f"  {mtype}: {cnt}")
    
    c.execute("SELECT COUNT(*) FROM word_morphemes")
    print(f"\nTotal rows: {c.fetchone()[0]}")
    
    # Phase 4: Build morpheme_form_counts for accurate registry counts
    print("\nPhase 4: Building morpheme_form_counts...")
    c.execute("DROP TABLE IF EXISTS morpheme_form_counts")
    c.execute("""
        CREATE TABLE morpheme_form_counts (
            mtype TEXT NOT NULL,
            morpheme TEXT NOT NULL,
            stype TEXT NOT NULL,
            form_count INTEGER NOT NULL,
            PRIMARY KEY (mtype, morpheme, stype)
        )
    """)
    
    # Count directly from word_morphemes via GROUP BY — no LIKE needed (1.4s vs 3h)
    stype_map = {'PREFIX': 'prefix', 'SUFFIX': 'suffix', 'ROOT': 'root', 'ENDING': 'ending'}
    
    c.execute("""
        SELECT mtype, morpheme, COUNT(DISTINCT lemma)
        FROM word_morphemes
        WHERE source != 'unknown'
        GROUP BY mtype, morpheme
    """)
    rows = c.fetchall()
    print(f"  Got {len(rows)} morpheme groups")
    
    count_rows = []
    for mtype_val, morph, cnt in rows:
        st = stype_map.get(mtype_val)
        if st and morph:
            count_rows.append((mtype_val, morph, st, cnt))
    
    c.executemany(
        "INSERT INTO morpheme_form_counts (mtype, morpheme, stype, form_count) VALUES (?, ?, ?, ?)",
        count_rows
    )
    conn.commit()
    print(f"  Written {len(count_rows)} count entries")
    
    conn.close()
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
