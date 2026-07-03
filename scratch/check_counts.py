import sqlite3
import os

DB_PATH = '/Users/alex/logos/data/language/ru_paradigms.sqlite3'

def check():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("--- Root Counts (Registry Style) ---")
    
    # Tikhonov
    c.execute("""
        SELECT COUNT(DISTINCT morpheme) 
        FROM word_morphemes 
        WHERE mtype = 'ROOT' AND source = 'tikhonov'
        AND is_blacklisted = 0 AND (proper_type IS NULL OR proper_type = '')
    """)
    print(f"Tikhonov (filtered): {c.fetchone()[0]}")
    
    # Algorithmic (OpenCorpora)
    c.execute("""
        SELECT COUNT(DISTINCT morpheme) 
        FROM word_morphemes 
        WHERE mtype = 'ROOT' AND source = 'algorithmic'
        AND is_blacklisted = 0 AND (proper_type IS NULL OR proper_type = '')
    """)
    print(f"OpenCorpora (filtered): {c.fetchone()[0]}")
    
    # Union (What UI currently shows if source is ignored)
    c.execute("""
        SELECT COUNT(DISTINCT morpheme) 
        FROM word_morphemes 
        WHERE mtype = 'ROOT'
    """)
    print(f"Current UI (Union, unfiltered): {c.fetchone()[0]}")

    conn.close()

if __name__ == "__main__":
    check()
