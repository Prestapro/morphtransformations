#!/usr/bin/env python3
"""Cover uncovered lemmas using known morpheme inventory. Optimized version.

Strategy: strip known affixes from both ends, check if remainder is a known root.
No brute-force search over all prefixes × suffixes × endings.
"""

import os
import sqlite3
import time
import sys

_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
DB_PATH = os.path.join(_ROOT, 'data', 'language', 'ru_paradigms.sqlite3')


def main():
    t0 = time.time()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Load known morpheme inventory
    print("Loading morpheme inventory...", flush=True)
    
    c.execute("SELECT DISTINCT morpheme FROM word_morphemes WHERE mtype='PREFIX' AND source='tikhonov'")
    prefix_set = {r[0] for r in c.fetchall()}
    
    c.execute("SELECT DISTINCT morpheme FROM word_morphemes WHERE mtype='ROOT' AND source='tikhonov'")
    root_set = {r[0] for r in c.fetchall()}
    
    c.execute("SELECT DISTINCT morpheme FROM word_morphemes WHERE mtype='SUFFIX' AND source='tikhonov'")
    suffix_set = {r[0] for r in c.fetchall()}
    
    c.execute("SELECT DISTINCT morpheme FROM word_morphemes WHERE mtype='ENDING' AND source='tikhonov'")
    ending_set = {r[0] for r in c.fetchall()}
    
    links = {'о', 'е', 'ё'}
    
    print(f"  P={len(prefix_set)} R={len(root_set)} S={len(suffix_set)} E={len(ending_set)}", flush=True)
    
    # Pre-compute max lengths for bounded iteration
    max_pfx = max((len(p) for p in prefix_set), default=0)
    max_sfx = max((len(s) for s in suffix_set), default=0)
    max_end = max((len(e) for e in ending_set), default=0)
    
    def try_decompose(w):
        """Fast decomposition: try stripping prefix, ending, suffix(es), check root."""
        if len(w) < 2:
            return None
        
        best = None
        
        # Generate prefix candidates: no prefix, or each valid prefix
        pfx_options = [(None, w)]
        for plen in range(1, min(max_pfx + 1, len(w))):
            cand = w[:plen]
            if cand in prefix_set:
                pfx_options.append((cand, w[plen:]))
        
        for pfx, after_pfx in pfx_options:
            if len(after_pfx) < 1:
                continue
            
            # Generate ending candidates: no ending, or each valid ending
            end_options = [(None, after_pfx)]
            for elen in range(1, min(max_end + 1, len(after_pfx))):
                cand = after_pfx[-elen:]
                if cand in ending_set:
                    end_options.append((cand, after_pfx[:-elen]))
            
            for end, after_end in end_options:
                if len(after_end) < 1:
                    continue
                
                # Try: remainder = root (no suffix)
                if after_end in root_set:
                    parts = []
                    if pfx: parts.append((pfx, 'PREFIX'))
                    parts.append((after_end, 'ROOT'))
                    if end: parts.append((end, 'ENDING'))
                    if best is None or len(parts) > len(best):
                        best = parts
                
                # Try: strip 1 suffix from the end of after_end
                for slen in range(1, min(max_sfx + 1, len(after_end))):
                    suf1 = after_end[-slen:]
                    if suf1 not in suffix_set:
                        continue
                    rem1 = after_end[:-slen]
                    if not rem1:
                        continue
                    
                    # rem1 = root?
                    if rem1 in root_set:
                        parts = []
                        if pfx: parts.append((pfx, 'PREFIX'))
                        parts.append((rem1, 'ROOT'))
                        parts.append((suf1, 'SUFFIX'))
                        if end: parts.append((end, 'ENDING'))
                        if best is None or len(parts) > len(best):
                            best = parts
                        continue
                    
                    # Try: strip 2nd suffix
                    for slen2 in range(1, min(max_sfx + 1, len(rem1))):
                        suf2 = rem1[-slen2:]
                        if suf2 not in suffix_set:
                            continue
                        rem2 = rem1[:-slen2]
                        if rem2 and rem2 in root_set:
                            parts = []
                            if pfx: parts.append((pfx, 'PREFIX'))
                            parts.append((rem2, 'ROOT'))
                            parts.append((suf2, 'SUFFIX'))
                            parts.append((suf1, 'SUFFIX'))
                            if end: parts.append((end, 'ENDING'))
                            if best is None or len(parts) > len(best):
                                best = parts
                
                # Try compound: root + link + root (+ optional suffix)
                for i in range(2, len(after_end) - 1):
                    r1 = after_end[:i]
                    if r1 not in root_set:
                        continue
                    mid = after_end[i:]
                    # root + link + root
                    if mid and mid[0] in links and len(mid) > 2:
                        r2_part = mid[1:]
                        if r2_part in root_set:
                            parts = []
                            if pfx: parts.append((pfx, 'PREFIX'))
                            parts.append((r1, 'ROOT'))
                            parts.append((mid[0], 'LINK'))
                            parts.append((r2_part, 'ROOT'))
                            if end: parts.append((end, 'ENDING'))
                            if best is None or len(parts) > len(best):
                                best = parts
                        # root + link + root + suffix
                        for slen in range(1, min(max_sfx + 1, len(r2_part))):
                            suf = r2_part[-slen:]
                            if suf in suffix_set:
                                r2 = r2_part[:-slen]
                                if r2 and r2 in root_set:
                                    parts = []
                                    if pfx: parts.append((pfx, 'PREFIX'))
                                    parts.append((r1, 'ROOT'))
                                    parts.append((mid[0], 'LINK'))
                                    parts.append((r2, 'ROOT'))
                                    parts.append((suf, 'SUFFIX'))
                                    if end: parts.append((end, 'ENDING'))
                                    if best is None or len(parts) > len(best):
                                        best = parts
        
        return best
    
    # Load uncovered
    c.execute("SELECT DISTINCT lemma, pos FROM word_morphemes WHERE source='unknown'")
    uncovered = c.fetchall()
    print(f"Uncovered: {len(uncovered)}", flush=True)
    
    newly_covered = 0
    still_uncovered = 0
    rows_insert = []
    rows_delete = []
    
    for i, (lemma, pos) in enumerate(uncovered):
        result = try_decompose(lemma.lower().strip())
        
        if result:
            rows_delete.append((lemma, pos))
            for pos_idx, (morph, mtype) in enumerate(result):
                rows_insert.append((lemma, pos, morph, mtype, pos_idx, 'algorithmic'))
            newly_covered += 1
        else:
            still_uncovered += 1
        
        if (i + 1) % 10000 == 0:
            print(f"  {i+1}/{len(uncovered)}  +{newly_covered} covered, {still_uncovered} unknown", flush=True)
    
    print(f"\n+{newly_covered} covered, {still_uncovered} still unknown", flush=True)
    
    # Update DB
    print("Updating DB...", flush=True)
    for lemma, pos in rows_delete:
        c.execute("DELETE FROM word_morphemes WHERE lemma=? AND pos=? AND source='unknown'", (lemma, pos))
    
    c.executemany(
        "INSERT INTO word_morphemes (lemma, pos, morpheme, mtype, position, source) VALUES (?, ?, ?, ?, ?, ?)",
        rows_insert
    )
    conn.commit()
    
    # Stats
    c.execute("SELECT source, COUNT(DISTINCT lemma) FROM word_morphemes GROUP BY source")
    print("\nFinal coverage:")
    for src, cnt in c.fetchall():
        print(f"  {src}: {cnt}")
    
    conn.close()
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
