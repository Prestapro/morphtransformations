import sqlite3
import math
import os

DB_PATH = '/Users/alex/logos/data/language/ru_paradigms.sqlite3'

def calculate_entropy(count):
    if count <= 1: return 0
    return math.log2(count)

def run_test():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    root = 'вод'
    c.execute("SELECT COUNT(DISTINCT lemma) FROM word_morphemes WHERE morpheme = ? AND mtype = 'ROOT'", (root,))
    cnt_root = c.fetchone()[0]
    h_root = calculate_entropy(cnt_root)
    print(f"1. Корень '{root}': {cnt_root} лемм. H = {h_root:.2f} бит")
    
    # Сценарий А: Движение/Транспорт (приставка 'про-')
    prefix = 'про'
    c.execute("""
        SELECT COUNT(DISTINCT wm1.lemma) 
        FROM word_morphemes wm1
        JOIN word_morphemes wm2 ON wm1.lemma = wm2.lemma
        WHERE wm1.morpheme = ? AND wm1.mtype = 'PREFIX'
          AND wm2.morpheme = ? AND wm2.mtype = 'ROOT'
    """, (prefix, root))
    cnt_prefix = c.fetchone()[0]
    h_prefix = calculate_entropy(cnt_prefix)
    print(f"2. Оператор '{prefix}-' + '{root}': {cnt_prefix} лемм. H = {h_prefix:.2f} бит. Сжатие: -{h_root - h_prefix:.2f} бит")

    # Сценарий Б: Субъект (суффикс '-ник')
    suffix = 'ник'
    c.execute("""
        SELECT COUNT(DISTINCT wm1.lemma) 
        FROM word_morphemes wm1
        JOIN word_morphemes wm2 ON wm1.lemma = wm2.lemma
        JOIN word_morphemes wm3 ON wm1.lemma = wm3.lemma
        WHERE wm1.morpheme = ? AND wm1.mtype = 'PREFIX'
          AND wm2.morpheme = ? AND wm2.mtype = 'ROOT'
          AND wm3.morpheme = ? AND wm3.mtype = 'SUFFIX'
    """, (prefix, root, suffix))
    cnt_full = c.fetchone()[0]
    h_full = calculate_entropy(cnt_full)
    print(f"3. Цепочка '{prefix}-' + '{root}' + '-{suffix}': {cnt_full} лемм. H = {h_full:.2f} бит. Сжатие: -{h_root - h_full:.2f} бит")

    # Сценарий В: Физика (еще один суффикс или префикс)
    # Посмотрим на 'полу-про-вод-ник'
    prefix2 = 'полу'
    c.execute("""
        SELECT COUNT(DISTINCT wm1.lemma) 
        FROM word_morphemes wm1
        JOIN word_morphemes wm2 ON wm1.lemma = wm2.lemma
        JOIN word_morphemes wm3 ON wm1.lemma = wm3.lemma
        JOIN word_morphemes wm4 ON wm1.lemma = wm4.lemma
        WHERE wm1.morpheme = ? AND wm1.mtype = 'PREFIX'
          AND wm2.morpheme = ? AND wm2.mtype = 'PREFIX'
          AND wm3.morpheme = ? AND wm3.mtype = 'ROOT'
          AND wm4.morpheme = ? AND wm4.mtype = 'SUFFIX'
    """, (prefix2, prefix, root, suffix))
    cnt_v = c.fetchone()[0]
    h_v = calculate_entropy(cnt_v)
    print(f"4. Сверхсжатие '{prefix2}-{prefix}-{root}-{suffix}': {cnt_v} лемм. H = {h_v:.2f} бит. Сжатие: -{h_root - h_v:.2f} бит")

    conn.close()

if __name__ == '__main__':
    run_test()
