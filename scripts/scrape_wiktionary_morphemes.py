#!/usr/bin/env python3
"""
Scrape Russian Wiktionary morpheme categories.
Extracts words grouped by suffix, prefix, and prefixoid.

Usage:
    python3 scrape_wiktionary_morphemes.py

Output:
    data/wiktionary_morphemes.json
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE_URL = "https://ru.wiktionary.org/w/api.php"
UA = "LogosMorphBot/1.0 (https://github.com/logos; alex@logos.dev)"
RATE_LIMIT = 0.25  # seconds between requests

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')


def api_get(params: dict) -> dict:
    """Make a GET request to the Wiktionary API with rate limiting."""
    params['format'] = 'json'
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    time.sleep(RATE_LIMIT)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))


def get_subcategories(cat_title: str) -> list[str]:
    """Get all subcategory titles under a category (handles pagination)."""
    subcats = []
    params = {
        'action': 'query',
        'list': 'categorymembers',
        'cmtitle': cat_title,
        'cmtype': 'subcat',
        'cmlimit': '500',
    }
    while True:
        data = api_get(params)
        for m in data['query']['categorymembers']:
            subcats.append(m['title'])
        if 'continue' in data:
            params['cmcontinue'] = data['continue']['cmcontinue']
        else:
            break
    return subcats


def get_category_pages(cat_title: str) -> list[str]:
    """Get all page titles (words) in a category (handles pagination)."""
    pages = []
    params = {
        'action': 'query',
        'list': 'categorymembers',
        'cmtitle': cat_title,
        'cmtype': 'page',
        'cmlimit': '500',
        'cmnamespace': '0',  # main namespace only
    }
    while True:
        data = api_get(params)
        for m in data['query']['categorymembers']:
            pages.append(m['title'])
        if 'continue' in data:
            params['cmcontinue'] = data['continue']['cmcontinue']
        else:
            break
    return pages


def extract_morpheme_name(cat_title: str, pattern: str) -> str:
    """Extract morpheme from category title.
    
    e.g. 'Категория:Русские слова с суффиксом -ость' -> '-ость'
    """
    if pattern in cat_title:
        return cat_title.split(pattern, 1)[1].strip()
    return cat_title


def scrape_morpheme_group(parent_cat: str, pattern: str, label: str) -> dict:
    """Scrape all subcategories of a morpheme type.
    
    Returns: {morpheme: [word1, word2, ...], ...}
    """
    print(f"\n{'='*60}")
    print(f"Scraping: {label}")
    print(f"Parent: {parent_cat}")
    print(f"{'='*60}")
    
    subcats = get_subcategories(parent_cat)
    print(f"Found {len(subcats)} subcategories")
    
    result = {}
    total_words = 0
    
    for i, subcat in enumerate(subcats, 1):
        morpheme = extract_morpheme_name(subcat, pattern)
        pages = get_category_pages(subcat)
        
        if pages:
            result[morpheme] = pages
            total_words += len(pages)
        
        if i % 20 == 0 or i == len(subcats):
            print(f"  [{i}/{len(subcats)}] {morpheme}: {len(pages)} words (total: {total_words:,})")
    
    print(f"Done: {len(result)} morphemes, {total_words:,} words")
    return result


def main():
    print("Wiktionary Russian Morpheme Scraper")
    print("=" * 60)
    
    data = {
        "meta": {
            "source": "ru.wiktionary.org",
            "date": time.strftime("%Y-%m-%d"),
            "description": "Russian words grouped by morpheme type from Wiktionary categories",
        },
        "suffixes": {},
        "prefixes": {},
        "prefixoids": {},
        "postfixes": {},
    }
    
    # 1. Suffixes (564 subcats — the biggest group)
    data["suffixes"] = scrape_morpheme_group(
        parent_cat="Категория:Русские слова по суффиксам",
        pattern="суффиксом ",
        label="Суффиксы (564 subcats)"
    )
    
    # 2. Prefixes (93 subcats)
    data["prefixes"] = scrape_morpheme_group(
        parent_cat="Категория:Русские слова по приставкам",
        pattern="приставкой ",
        label="Приставки (93 subcats)"
    )
    
    # 3. Prefixoids (90 subcats) — авиа-, авто-, аэро-
    data["prefixoids"] = scrape_morpheme_group(
        parent_cat="Категория:Русские слова по префиксоидам",
        pattern="префиксоидом ",
        label="Префиксоиды (90 subcats)"
    )
    
    # 4. Postfixes (7 subcats) — -ся, -то, -нибудь
    data["postfixes"] = scrape_morpheme_group(
        parent_cat="Категория:Русские слова по постфиксам",
        pattern="постфиксом ",
        label="Постфиксы (7 subcats)"
    )
    
    # Summary stats
    total_morphemes = sum(len(data[k]) for k in ["suffixes", "prefixes", "prefixoids", "postfixes"])
    total_words = sum(sum(len(v) for v in data[k].values()) for k in ["suffixes", "prefixes", "prefixoids", "postfixes"])
    
    data["meta"]["total_morphemes"] = total_morphemes
    data["meta"]["total_words"] = total_words
    
    print(f"\n{'='*60}")
    print(f"TOTAL: {total_morphemes} morphemes, {total_words:,} words")
    print(f"  Suffixes:   {len(data['suffixes'])} morphemes")
    print(f"  Prefixes:   {len(data['prefixes'])} morphemes")
    print(f"  Prefixoids: {len(data['prefixoids'])} morphemes")
    print(f"  Postfixes:  {len(data['postfixes'])} morphemes")
    
    # Save
    out_path = os.path.join(OUT_DIR, 'wiktionary_morphemes.json')
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"\nSaved to: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
