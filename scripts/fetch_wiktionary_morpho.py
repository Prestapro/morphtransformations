#!/usr/bin/env python3
"""Extract full morphemic decompositions from ru.wiktionary.org via API.

Parses {{морфо-ru|...}} templates from article wikitext.
Output: JSON with word → [{"type": "PREFIX", "value": "пере"}, ...] mapping.

Convention:
  - "пере-" (trailing dash) = PREFIX
  - "пис" (no marker) = ROOT  
  - "-ыва" (leading dash) = SUFFIX
  - "+е" (leading plus) = ENDING
  - "и=т" or standalone between roots = LINK (interfix)
  - "-∅" or "+∅" = zero morpheme (skip)

Usage:
  python3 scripts/fetch_wiktionary_morpho.py [--limit N] [--resume FILE]
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUT_PATH = os.path.join(OUT_DIR, 'wiktionary_decompositions.json')

API_BASE = 'https://ru.wiktionary.org/w/api.php'
BATCH = 50  # titles per API call (max 50)
DELAY = 1.5  # seconds between requests
MAX_RETRIES = 3

# Parse {{морфо-ru|на-|низ|-а|+ть|и=т}} → [(type, value), ...]
_MORPHO_RE = re.compile(r'\{\{морфо-ru\|([^}]+)\}\}')


def parse_morpho_template(tmpl_content: str):
    """Parse the inside of {{морфо-ru|...}} into morpheme list."""
    parts = tmpl_content.split('|')
    result = []
    
    for p in parts:
        p = p.strip()
        if not p:
            continue
        
        # Skip metadata flags like "и=т", "и=т3"
        if re.match(r'^и=', p):
            continue
        
        # Skip zero morphemes
        if p in ('-∅', '+∅', '∅'):
            continue
        
        # PREFIX: trailing dash "пере-"
        if p.endswith('-') and not p.startswith('-') and not p.startswith('+'):
            val = p.rstrip('-')
            if val:
                result.append(('PREFIX', val.lower()))
        # ENDING: leading plus "+ый"
        elif p.startswith('+'):
            val = p.lstrip('+')
            if val:
                result.append(('ENDING', val.lower()))
        # SUFFIX: leading dash "-ыва"
        elif p.startswith('-'):
            val = p.lstrip('-')
            if val:
                result.append(('SUFFIX', val.lower()))
        # ROOT: no marker
        else:
            result.append(('ROOT', p.lower()))
    
    return result


def fetch_pages_wikitext(titles):
    """Fetch wikitext for multiple pages in one API call, with retry on 429."""
    params = {
        'action': 'query',
        'titles': '|'.join(titles),
        'prop': 'revisions',
        'rvprop': 'content',
        'rvslots': 'main',
        'format': 'json',
        'formatversion': '2',
    }
    url = API_BASE + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'MorphoExtractor/1.0 (logos project)'})
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES:
                wait = 2 ** (attempt + 1)  # 2, 4, 8 seconds
                time.sleep(wait)
                continue
            print(f'  API error: {e}', flush=True)
            return {}
        except Exception as e:
            print(f'  API error: {e}', flush=True)
            return {}
    
    result = {}
    for page in data.get('query', {}).get('pages', []):
        title = page.get('title', '')
        if page.get('missing'):
            continue
        revisions = page.get('revisions', [])
        if not revisions:
            continue
        content = revisions[0].get('slots', {}).get('main', {}).get('content', '')
        result[title] = content
    
    return result


def extract_morpho_from_wikitext(wikitext: str):
    """Extract first {{морфо-ru|...}} template and parse it."""
    m = _MORPHO_RE.search(wikitext)
    if not m:
        return None
    return parse_morpho_template(m.group(1))


def get_all_russian_words(limit=0):
    """Get Russian word list from the category via API (generator)."""
    params = {
        'action': 'query',
        'list': 'categorymembers',
        'cmtitle': 'Категория:Русский язык',
        'cmlimit': '500',
        'cmnamespace': '0',
        'cmtype': 'page',
        'format': 'json',
        'formatversion': '2',
    }
    
    all_titles = []
    cont = None
    
    while True:
        p = dict(params)
        if cont:
            p['cmcontinue'] = cont
        
        url = API_BASE + '?' + urllib.parse.urlencode(p)
        req = urllib.request.Request(url, headers={'User-Agent': 'MorphoExtractor/1.0 (logos project)'})
        
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f'  Category API error: {e}', flush=True)
            break
        
        members = data.get('query', {}).get('categorymembers', [])
        for m in members:
            title = m.get('title', '')
            # Only Cyrillic words (skip templates, categories, etc.)
            if title and re.match(r'^[а-яёА-ЯЁ]', title):
                all_titles.append(title)
        
        cont_data = data.get('continue', {})
        cont = cont_data.get('cmcontinue')
        if not cont:
            break
        
        if limit and len(all_titles) >= limit:
            all_titles = all_titles[:limit]
            break
        
        if len(all_titles) % 5000 < 500:
            print(f'  Collected {len(all_titles)} titles...', flush=True)
        
        time.sleep(0.2)
    
    return all_titles


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='Max words to fetch (0=all)')
    parser.add_argument('--resume', type=str, default='', help='Resume from existing JSON file')
    parser.add_argument('--wordlist', type=str, default='', help='Use lemma list from DB instead of Wiktionary category')
    args = parser.parse_args()
    
    t0 = time.time()
    
    # Load existing results if resuming
    decompositions = {}
    if args.resume and os.path.exists(args.resume):
        with open(args.resume, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        decompositions = existing.get('decompositions', {})
        print(f'Resumed with {len(decompositions)} existing entries', flush=True)
    
    # Get word list
    if args.wordlist:
        import sqlite3
        conn = sqlite3.connect(args.wordlist)
        c = conn.cursor()
        c.execute("SELECT DISTINCT lemma FROM paradigms WHERE lemma GLOB '[а-яёА-ЯЁ]*'")
        titles = [row[0] for row in c.fetchall()]
        conn.close()
        print(f'Loaded {len(titles)} lemmas from DB', flush=True)
    else:
        print('Fetching word list from Wiktionary category...', flush=True)
        titles = get_all_russian_words(args.limit)
    
    print(f'Total titles to process: {len(titles)}', flush=True)
    
    # Skip already processed
    if decompositions:
        titles = [t for t in titles if t.lower() not in decompositions]
        print(f'After filtering known: {len(titles)} remaining', flush=True)
    
    # Process in batches
    found = 0
    no_morpho = 0
    errors = 0
    
    for i in range(0, len(titles), BATCH):
        batch = titles[i:i+BATCH]
        
        try:
            pages = fetch_pages_wikitext(batch)
        except Exception as e:
            print(f'  Batch error at {i}: {e}', flush=True)
            errors += len(batch)
            continue
        
        for title, wikitext in pages.items():
            morphemes = extract_morpho_from_wikitext(wikitext)
            if morphemes and len(morphemes) > 0:
                decompositions[title.lower()] = [{'type': t, 'value': v} for t, v in morphemes]
                found += 1
            else:
                no_morpho += 1
        
        # Progress
        done = i + len(batch)
        if done % 500 == 0 or done == len(titles):
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            print(f'  {done}/{len(titles)} ({rate:.0f}/s) found={found} no_morpho={no_morpho} errors={errors}', flush=True)
        
        # Save checkpoint every 5000
        if done % 5000 == 0 and done > 0:
            _save(decompositions)
            print(f'  Checkpoint saved: {len(decompositions)} entries', flush=True)
        
        time.sleep(DELAY)
    
    _save(decompositions)
    print(f'\nDone in {time.time()-t0:.1f}s')
    print(f'Total decompositions: {len(decompositions)}')
    print(f'Found: {found}, No morpho template: {no_morpho}, Errors: {errors}')


def _save(decompositions):
    os.makedirs(OUT_DIR, exist_ok=True)
    out = {
        'meta': {
            'source': 'ru.wiktionary.org',
            'description': 'Full morphemic decompositions from {{морфо-ru}} templates',
            'total': len(decompositions),
        },
        'decompositions': decompositions,
    }
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
