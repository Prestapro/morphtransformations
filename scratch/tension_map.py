import sqlite3
import math
import os

DB_PATH = '/Users/alex/logos/data/language/ru_paradigms.sqlite3'

def get_entropy(conn, word):
    c = conn.cursor()
    word = word.lower().strip(".,!?;:\"«»—…()")
    if not word: return 0.0
    variants = [word]
    if 'е' in word: variants.append(word.replace('е', 'ё'))
    lemmas = set()
    for v in variants:
        c.execute("SELECT DISTINCT lemma FROM paradigms WHERE form = ?", (v,))
        for r in c.fetchall(): lemmas.add(r[0])
    if not lemmas:
        for v in variants:
            c.execute("SELECT COUNT(*) FROM word_morphemes WHERE lemma = ?", (v,))
            cnt = c.fetchone()[0]
            if cnt > 0: return math.log2(cnt)
        return 15.0 
    total_decomps = 0
    for lemma in lemmas:
        c.execute("SELECT COUNT(*) FROM word_morphemes WHERE lemma = ?", (lemma,))
        cnt = c.fetchone()[0]
        total_decomps += (cnt if cnt > 0 else 1)
    return math.log2(total_decomps) if total_decomps > 0 else 0.0

def analyze_little_prince():
    conn = sqlite3.connect(DB_PATH)
    text = "Вот мой секрет, он очень прост: зорко одно лишь сердце. Самого главного глазами не увидишь. Мы в ответе за тех, кого приручили."
    
    words = text.split()
    results = []
    for w in words:
        h = get_entropy(conn, w)
        results.append((w, h))
    
    print(f"{'Слово':<15} | {'H':<6} | {'Визуализация'}")
    print("-" * 45)
    for w, h in results:
        bar = "█" * int(h * 2)
        print(f"{w:<15} | {h:<6.2f} | {bar}")
    conn.close()

if __name__ == '__main__':
    analyze_little_prince()
