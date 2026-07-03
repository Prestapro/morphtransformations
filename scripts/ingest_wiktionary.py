import json
import sqlite3
import os
import sys

WIKT_PATH = '/Users/alex/logos/morphtransformations/data/wiktionary_decompositions.json'
DB_PATH = '/Users/alex/logos/data/language/ru_paradigms.sqlite3'

def ingest():
    if not os.path.exists(WIKT_PATH):
        print(f"Error: {WIKT_PATH} not found")
        return

    print(f"Loading Wiktionary data from {WIKT_PATH}...")
    with open(WIKT_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    decompositions = data.get('decompositions', {})
    print(f"  Got {len(decompositions)} lemmas")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Get POS mapping from paradigms table
    print("Loading POS mapping from paradigms table...")
    c.execute("SELECT DISTINCT lemma, pos FROM paradigms")
    lemma_pos = {row[0]: row[1] for row in c.fetchall()}
    print(f"  Mapped {len(lemma_pos)} lemmas to POS")
    
    # 2. Delete existing wiktionary entries
    print("Cleaning old Wiktionary data from database...")
    c.execute("DELETE FROM word_morphemes WHERE source = 'wiktionary'")
    print(f"  Removed {c.rowcount} old rows")
    
    # 3. Prepare rows
    print("Preparing rows for insertion...")
    rows = []
    for lemma, parts in decompositions.items():
        pos = lemma_pos.get(lemma, 'UNKNOWN')
        for i, part in enumerate(parts):
            morpheme = part['value'].lower().strip()
            # Clean morpheme: remove hyphens, stars, etc.
            morpheme = morpheme.replace('-', '').replace('*', '').strip()
            if not morpheme:
                continue
                
            mtype = part['type'].upper()
            # Map type to our internal types
            # Wiktionary uses PREFIX, ROOT, SUFFIX, ENDING, INTERFIX, POSTFIX
            if mtype == 'INTERFIX':
                mtype = 'LINK'
            elif mtype == 'POSTFIX':
                mtype = 'SUFFIX' # or keep as POSTFIX? Our UI expects PREFIX, ROOT, SUFFIX, ENDING, LINK
            
            rows.append((lemma, pos, morpheme, mtype, i, 'wiktionary'))
            
    print(f"Inserting {len(rows)} rows...")
    batch_size = 10000
    for i in range(0, len(rows), batch_size):
        c.executemany(
            "INSERT INTO word_morphemes (lemma, pos, morpheme, mtype, position, source) VALUES (?, ?, ?, ?, ?, ?)",
            rows[i:i+batch_size]
        )
        print(f"  Inserted {min(i+batch_size, len(rows))} / {len(rows)}")
    
    # 4. Set is_blacklisted (common prepositions/conjunctions)
    print("Applying blacklist filters...")
    blacklist = {'в', 'на', 'с', 'к', 'и', 'а', 'о', 'у', 'я', 'за', 'по', 'до', 'об', 'от', 'из', 'без'}
    for b in blacklist:
        c.execute("UPDATE word_morphemes SET is_blacklisted = 1 WHERE source = 'wiktionary' AND mtype = 'ROOT' AND morpheme = ?", (b,))
    
    # 5. Set proper_type for capitalized lemmas (if not already handled)
    # Actually, we can check if POS is 'PROPN' or if first letter is upper case and word exists in lowercase form
    print("Setting proper_type for names...")
    c.execute("""
        UPDATE word_morphemes 
        SET proper_type = 'NAME' 
        WHERE source = 'wiktionary' 
        AND (pos = 'PROPN' OR lemma GLOB '[А-Я]*')
    """)
    
    conn.commit()
    
    # Final stats
    print("\nVerification:")
    c.execute("SELECT mtype, COUNT(DISTINCT morpheme) FROM word_morphemes WHERE source = 'wiktionary' GROUP BY mtype")
    for mtype, cnt in c.fetchall():
        print(f"  {mtype}: {cnt} unique")
        
    c.execute("SELECT COUNT(DISTINCT lemma) FROM word_morphemes WHERE source = 'wiktionary'")
    print(f"  Total unique lemmas: {c.fetchone()[0]}")
    
    conn.close()
    print("Ingestion complete!")

if __name__ == '__main__':
    ingest()
