import sqlite3
import math
import os

DB_PATH = '/Users/alex/logos/data/language/ru_paradigms.sqlite3'

def get_word_entropy(conn, word):
    c = conn.cursor()
    # 1. Считаем количество способов разложить слово на морфемы (структурная энтропия)
    c.execute("SELECT COUNT(DISTINCT source) FROM word_morphemes WHERE lemma = ?", (word.lower(),))
    sources = c.fetchone()[0]
    
    # 2. Считаем количество уникальных корней/разборов (семантическая энтропия в нашей модели)
    c.execute("SELECT COUNT(*) FROM word_morphemes WHERE lemma = ?", (word.lower(),))
    rows = c.fetchone()[0]
    
    if rows <= 1: return 0.0
    return math.log2(rows)

def analyze_sentence(text):
    conn = sqlite3.connect(DB_PATH)
    words = text.replace('.', '').split()
    
    print(f"Анализ профиля: '{text}'\n")
    print(f"{'Слово':<15} | {'Энтропия (H)':<12} | {'Статус'}")
    print("-" * 45)
    
    total_h = 0
    for w in words:
        h = get_word_entropy(conn, w)
        status = "ВЫСОКАЯ (naked)" if h > 4 else "СЖАТАЯ (operator)" if h > 0 else "ОПРЕДЕЛЕНА"
        print(f"{w:<15} | {h:<12.2f} | {status}")
        total_h += h
        
    print("-" * 45)
    print(f"Суммарная семантическая неопределенность: {total_h:.2f} бит")
    conn.close()

if __name__ == '__main__':
    analyze_sentence("Проводник пришёл в заводской цех")
