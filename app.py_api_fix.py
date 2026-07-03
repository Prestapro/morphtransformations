@app.post("/api/entropy_map")
async def api_entropy_map(req: TensionMapRequest):
    try:
        import sqlite3
        import math
        from pathlib import Path
        db_path = Path(__file__).resolve().parent.parent / 'data' / 'language' / 'ru_paradigms.sqlite3'
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        
        words = req.text.split()
        results = []
        in_quotes = False
        
        OPERATOR_SIGNALS = {
            "но": "contrast", "однако": "contrast", "зато": "contrast", "а": "contrast",
            "именно": "focus", "только": "focus", "лишь": "focus",
            "потому": "causal", "поэтому": "causal", "ибо": "causal",
            "и": "connective", "да": "connective"
        }
        
        i = 0
        while i < len(words):
            raw_w = words[i]
            word_clean = raw_w.lower().strip(".,!?;:\"«»—…()")
            if not word_clean: 
                i += 1
                continue
            
            # Dialogue detection
            if '"' in raw_w or '«' in raw_w or '»' in raw_w:
                in_quotes = not in_quotes
            is_dialogue = in_quotes or raw_w.startswith('—') or raw_w.startswith('-')
            
            # Entity detection
            is_entity = False
            entity_lemma = word_clean
            if raw_w[0].isupper():
                c.execute("SELECT grammemes, lemma FROM paradigms WHERE form = ?", (word_clean,))
                rows = c.fetchall()
                for grams, lemma in rows:
                    if any(x in grams for x in ['Name', 'Surn', 'Patr']) or ('anim' in grams and 'NOUN' in grams):
                        is_entity = True
                        entity_lemma = lemma
                        break
            
            # FIO Merging (Lookahead)
            display_word = raw_w
            if is_entity and i + 1 < len(words):
                next_raw = words[i+1]
                next_clean = next_raw.lower().strip(".,!?;:\"«»—…()")
                if next_raw and next_raw[0].isupper():
                    c.execute("SELECT grammemes FROM paradigms WHERE form = ?", (next_clean,))
                    next_rows = c.fetchall()
                    is_next_name = False
                    for (ngrams,) in next_rows:
                        if any(x in ngrams for x in ['Name', 'Surn', 'Patr']):
                            is_next_name = True
                            break
                    if is_next_name:
                        display_word += " " + next_raw
                        i += 1 # Skip next word in main loop
            
            # Entropy calculation
            variants = [word_clean]
            if 'е' in word_clean: variants.append(word_clean.replace('е', 'ё'))
            lemmas = set()
            for v in variants:
                c.execute("SELECT DISTINCT lemma FROM paradigms WHERE form = ?", (v,))
                for (l,) in c.fetchall(): lemmas.add(l)
            
            if not lemmas:
                # Morphological entropy fallback
                found_in_morph = False
                c_morph = conn.cursor()
                for v in variants:
                    suffix_len = min(4, len(v))
                    if suffix_len >= 2:
                        suffix = v[-suffix_len:]
                        c_morph.execute("SELECT probability FROM suffix_stats WHERE suffix = ?", (suffix,))
                        row = c_morph.fetchone()
                        if row:
                            h = -math.log2(row[0]) if row[0] > 0 else 10.0
                            found_in_morph = True
                            break
                if not found_in_morph: h = 10.0
            else:
                total_decomps = 0
                for lemma in lemmas:
                    c.execute("SELECT COUNT(*) FROM word_morphemes WHERE lemma = ?", (lemma,))
                    cnt = c.fetchone()[0]
                    total_decomps += (cnt if cnt > 0 else 1)
                h = math.log2(total_decomps) if total_decomps > 0 else 0.0
                
            results.append({
                "word": display_word,
                "clean": entity_lemma, # Use lemma as key for filtering
                "h": round(h, 2),
                "signal_type": OPERATOR_SIGNALS.get(word_clean, None),
                "is_entity": is_entity,
                "is_dialogue": is_dialogue
            })
            i += 1
            
        conn.close()
        return {"status": "success", "data": results}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
