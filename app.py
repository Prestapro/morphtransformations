import sys
import re
import json
import os
import sqlite3
import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent directory to sys.path so we can import engine
PARENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PARENT_DIR))

try:
    from engine.language.inflector import inflect as db_inflect, agree_adjective, _get_conn, generate_feminitive as db_generate_feminitive
except ImportError:
    # Fallback/stub if not running inside the logos workspace
    db_inflect = None
    agree_adjective = None
    _get_conn = None
    db_generate_feminitive = None

app = FastAPI(
    title="Morphological Transformations Web Demo",
    description="Interactive visualization of Russian word inflections, feminitive generation, and morphotactic rules.",
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



POS_NAMES = {
    "NOUN": "существительное",
    "ADJF": "прилагательное (полное)",
    "ADJS": "прилагательное (краткое)",
    "COMP": "компаратив",
    "VERB": "глагол (личная форма)",
    "INFN": "глагол (инфинитив)",
    "PRTF": "причастие (полное)",
    "PRTS": "причастие (краткое)",
    "GRND": "деепричастие",
    "NUMR": "числительное",
    "ADVB": "наречие",
    "NPRO": "местоимение-существительное",
    "PRED": "предикатив",
    "PREP": "предлог",
    "CONJ": "союз",
    "PRCL": "частица",
    "INTJ": "междометие"
}

class InflectRequest(BaseModel):
    word: str
    grammemes: str
    pos: str | None = None

class AnalyzeRequest(BaseModel):
    word: str

class FeminitiveRequest(BaseModel):
    word: str
    style: str  # 'colloquial' or 'official'

class DecomposeRequest(BaseModel):
    word: str

class CognatesRequest(BaseModel):
    word: str

class ParadigmRequest(BaseModel):
    word: str

class SuffixStatsRequest(BaseModel):
    suffix: str

class MorphemeSearchRequest(BaseModel):
    morpheme: str
    morpheme_type: str  # 'prefix', 'suffix', 'ending', 'root', 'any'
    page: int = 1
    page_size: int = 5000



@app.post("/api/inflect")
def api_inflect(req: InflectRequest):
    if db_inflect is None:
        raise HTTPException(status_code=500, detail="Database inflector is unavailable.")
        
    try:
        from engine.language.inflector import _cached_paradigm, _cached_reverse_lookup, _inflect_from_paradigm
        
        word_lower = req.word.strip().lower()
        gram_set = set(g.strip() for g in req.grammemes.split(",") if g.strip())
        
        # Collect all unique interpretations: (lemma, pos)
        interpretations_list = []
        
        # 1. Try word as lemma
        lemma_rows = _cached_paradigm(word_lower)
        if lemma_rows:
            pos_set = set(r[0] for r in lemma_rows)
            for pos in pos_set:
                interpretations_list.append((word_lower, pos))
                
        # 2. Try reverse lookup (inflected forms)
        reverse = _cached_reverse_lookup(word_lower)
        if reverse:
            for lemma, pos, _gram_str, _form in reverse:
                if (lemma, pos) not in interpretations_list:
                    interpretations_list.append((lemma, pos))
                    
        # Apply POS constraint filter if passed
        if req.pos:
            interpretations_list = [item for item in interpretations_list if item[1] == req.pos]

        # 3. If no interpretations found, fallback to direct inflect
        if not interpretations_list:
            res = db_inflect(req.word, gram_set, pos_constraint=req.pos)
            if res:
                return {
                    "word": req.word,
                    "result": res,
                    "interpretations": [
                        {
                            "lemma": req.word,
                            "pos": req.pos if req.pos else "НЕИЗВЕСТНО",
                            "result": res,
                            "applicable": True
                        }
                    ]
                }
            return {"word": req.word, "result": req.word, "warning": "Слово не найдено в парадигмах"}

        # 4. Generate inflection for each interpretation
        interpretations = []
        for lemma, pos in interpretations_list:
            rows = _cached_paradigm(lemma)
            res = _inflect_from_paradigm(rows, frozenset(gram_set), pos_constraint=pos)
            
            # Check for imperfective verb future tense (analytic future)
            is_verb = pos in ("VERB", "INFN")
            is_impf = any("impf" in r[1] for r in rows)
            is_futr = "futr" in gram_set
            
            if not res and is_verb and is_impf and is_futr:
                # Resolve auxiliary 'быть' form based on target grammemes
                aux = "будет"  # default
                if "1per" in gram_set:
                    aux = "буду" if "sing" in gram_set or "plur" not in gram_set else "будем"
                elif "2per" in gram_set:
                    aux = "будешь" if "sing" in gram_set or "plur" not in gram_set else "будете"
                elif "3per" in gram_set:
                    aux = "будет" if "sing" in gram_set or "plur" not in gram_set else "будут"
                
                # Check explicit numbers
                if "plur" in gram_set:
                    if "1per" in gram_set: aux = "будем"
                    elif "2per" in gram_set: aux = "будете"
                    else: aux = "будут"
                elif "sing" in gram_set:
                    if "1per" in gram_set: aux = "буду"
                    elif "2per" in gram_set: aux = "будешь"
                    else: aux = "будет"
                    
                res = f"{aux} {lemma}"
                
            pos_ru = POS_NAMES.get(pos, pos.lower())
            
            if res:
                interpretations.append({
                    "lemma": lemma,
                    "pos": pos_ru,
                    "result": res,
                    "applicable": True
                })
            else:
                interpretations.append({
                    "lemma": lemma,
                    "pos": pos_ru,
                    "result": req.word,
                    "applicable": False,
                    "reason": f"Грамматический таргет неприменим к части речи: {pos_ru}"
                })
                
        # Select primary result (first applicable)
        primary_res = req.word
        warning = None
        applicable_items = [item for item in interpretations if item["applicable"]]
        
        if applicable_items:
            primary_res = applicable_items[0]["result"]
        else:
            warning = "Грамматический таргет неприменим ни к одной из трактовок слова"
            
        return {
            "word": req.word,
            "result": primary_res,
            "interpretations": interpretations,
            "warning": warning
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest):
    if db_inflect is None:
        raise HTTPException(status_code=500, detail="Database inflector is unavailable.")
        
    try:
        from engine.language.inflector import _cached_paradigm, _cached_reverse_lookup
        word_lower = req.word.strip().lower()
        if not word_lower:
            return {"interpretations": []}
            
        interpretations_list = []
        
        # 1. Try word as lemma
        lemma_rows = _cached_paradigm(word_lower)
        if lemma_rows:
            pos_set = set(r[0] for r in lemma_rows)
            for pos in pos_set:
                interpretations_list.append((word_lower, pos))
                
        # 2. Try reverse lookup
        reverse = _cached_reverse_lookup(word_lower)
        if reverse:
            for lemma, pos, _gram_str, _form in reverse:
                if (lemma, pos) not in interpretations_list:
                    interpretations_list.append((lemma, pos))
                    
        # Map to response format
        interpretations = []
        for lemma, pos in interpretations_list:
            interpretations.append({
                "lemma": lemma,
                "pos": pos,
                "pos_ru": POS_NAMES.get(pos, pos.lower())
            })
            
        return {"interpretations": interpretations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feminitive")
def api_feminitive(req: FeminitiveRequest):
    if db_generate_feminitive is None:
        raise HTTPException(status_code=500, detail="Database inflector is unavailable.")
    res = db_generate_feminitive(req.word, req.style)
    if "error" in res:
        return {"error": res["error"]}
    return res

@app.get("/api/rules")
def api_rules():
    return {
        "rules": [
            {
                "suffix": "ец (гласная)",
                "rule": "ец -> ейка",
                "example": "европеец -> европейка",
                "desc": "Применяется, когда перед суффиксом 'ец' идет гласная буква (согласование звучности)."
            },
            {
                "suffix": "ец (согласная)",
                "rule": "ец -> ка",
                "example": "американец -> американка",
                "desc": "Применяется, когда перед суффиксом 'ец' идет согласная."
            },
            {
                "suffix": "тель",
                "rule": "тель -> тельница",
                "example": "учитель -> учительница",
                "desc": "Регулярный суффикс профессий/деятелей женского рода."
            },
            {
                "suffix": "ик",
                "rule": "ик -> ица",
                "example": "художник -> художница",
                "desc": "Классическое изменение окончания для деятелей искусства и науки."
            },
            {
                "suffix": "Согласный",
                "rule": "+ ка",
                "example": "космонавт -> космонавтка",
                "desc": "Универсальный разговорный суффикс образования феминитивов."
            }
        ]
    }

class ExecuteRequest(BaseModel):
    code: str
    env: dict | None = None
    runtime: dict | None = None


@app.post("/api/execute")
def api_execute(req: ExecuteRequest):
    try:
        from engine.codetools.intent_executor import handle_directive, TimeLiteral
        
        # Build environment and runtime settings
        env_dict = req.env or {}
        env = {}
        # Parse time if passed as a string or fallback to current local time
        if "current_time" in env_dict and env_dict["current_time"]:
            ct = env_dict["current_time"]
            match = re.search(r"(\d{1,2}):(\d{2})", str(ct))
            if match:
                env["current_time"] = TimeLiteral(hour=int(match.group(1)), minute=int(match.group(2)))
        else:
            now = datetime.datetime.now()
            env["current_time"] = TimeLiteral(hour=now.hour, minute=now.minute)

        # Forward other client environment parameters
        for key in ("date", "language", "timezone"):
            if key in env_dict:
                env[key] = env_dict[key]
            
        runtime = req.runtime or {"target": "browser"}
        
        # 1. Try visual shape/time directives if explicitly requested
        is_directive = False
        directive_verbs = {"показать", "нарисовать", "отобразить", "вывести", "покажи", "нарисуй", "выведи", "отобрази"}
        code_lower = req.code.lower()
        if "если" in code_lower or any(verb in code_lower for verb in directive_verbs):
            is_directive = True

        if is_directive:
            result = handle_directive(req.code, env, runtime)
            if result is not None:
                return result

        # 2. Try geometry solving
        try:
            from engine.nlu.handlers.geometry_handler import handle_geometry
            geom_res = handle_geometry(req.code)
            if geom_res is not None:
                return {
                    "status": "success",
                    "type": "terminal_ansi",
                    "payload": geom_res,
                    "svg": ""
                }
        except Exception:
            pass

        # 3. Try math routing and solving
        try:
            from engine.math.math_router import route_math, MathKind
            from engine.math.math_normalizer import MathNormalizer
            mq = route_math(req.code)
            if mq.kind != MathKind.OTHER:
                norm = MathNormalizer()
                normalized = norm.normalize(req.code, mq.kind, mq.meta)
                math_res = norm.evaluate(normalized)
                if math_res is not None:
                    if isinstance(math_res, bool):
                        payload_text = "Верно" if math_res else "Неверно"
                    else:
                        payload_text = str(math_res)
                    return {
                        "status": "success",
                        "type": "terminal_ansi",
                        "payload": payload_text,
                        "svg": ""
                    }
        except Exception:
            pass

        # 4. Try visual shape/time directives as a secondary fallback if not explicitly gated
        if not is_directive:
            result = handle_directive(req.code, env, runtime)
            if result is not None:
                return result

        # 5. Fallback to general Russian code interpreter
        from engine.codetools.rus_lang.interpreter import run_program
        res = run_program(req.code)
        if res["status"] == "success":
            output_text = "\n".join(res["output"]) if res["output"] else "Код выполнен успешно (нет вывода)."
            return {
                "status": "success",
                "type": "terminal_ansi",
                "payload": output_text,
                "svg": ""
            }
        elif res["status"] in ("parse_error", "runtime_error"):
            return {
                "status": "unsupported",
                "message": f"Ошибка интерпретатора: {res['error']}"
            }
        return {
            "status": "unsupported",
            "message": "Фраза не распознана как поддерживаемая директива или условие."
        }
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --------------- Lazy-load globals ---------------

_morph_algebra = None
def _get_morph_algebra():
    global _morph_algebra
    if _morph_algebra is None:
        from engine.hdc.morpheme_algebra import MorphemeAlgebra
        _morph_algebra = MorphemeAlgebra()
    return _morph_algebra

_tikhonov_data = None
def _get_tikhonov_data():
    global _tikhonov_data
    if _tikhonov_data is None:
        path = os.path.join(str(PARENT_DIR), 'data', 'tikhonov_morphemes.json')
        with open(path, 'r', encoding='utf-8') as f:
            _tikhonov_data = json.load(f)
    return _tikhonov_data

_ALTERNATION_PAIRS = [
    ('г', 'ж'), ('к', 'ч'), ('х', 'ш'),
    ('д', 'ж'), ('т', 'ч'), ('т', 'щ'),
    ('з', 'ж'), ('с', 'ш'),
]


@app.post("/api/decompose")
def api_decompose(req: DecomposeRequest):
    try:
        algebra = _get_morph_algebra()
        raw = algebra.decompose(req.word)
        morphemes = [{"type": mtype, "value": mval} for mtype, mval in raw]
        source = "fallback" if raw == [("ROOT", req.word)] else "tikhonov"
        return {"word": req.word, "morphemes": morphemes, "source": source}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cognates")
def api_cognates(req: CognatesRequest):
    try:
        algebra = _get_morph_algebra()
        raw = algebra.decompose(req.word)
        root = None
        for mtype, mval in raw:
            if mtype == "ROOT":
                root = mval
                break
        if root is None:
            return {"word": req.word, "root": None, "cognates": [], "total": 0}

        data = _get_tikhonov_data()
        roots_index = data.get("roots_index", {})

        cognates = roots_index.get(root, [])
        if not cognates:
            # Try consonant alternations
            for a, b in _ALTERNATION_PAIRS:
                if root.endswith(a):
                    alt_root = root[:-1] + b
                    cognates = roots_index.get(alt_root, [])
                    if cognates:
                        root = alt_root
                        break
                elif root.endswith(b):
                    alt_root = root[:-1] + a
                    cognates = roots_index.get(alt_root, [])
                    if cognates:
                        root = alt_root
                        break

        return {"word": req.word, "root": root, "cognates": cognates, "total": len(cognates)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/paradigm")
def api_paradigm(req: ParadigmRequest):
    try:
        from engine.language.inflector import _cached_paradigm
        word_lower = req.word.strip().lower()
        rows = _cached_paradigm(word_lower)
        if not rows:
            return {"word": req.word, "lemma": word_lower, "pos": None, "forms": []}

        forms = []
        pos_found = None
        for pos, grammemes, form in rows:
            if pos_found is None:
                pos_found = pos
            forms.append({"pos": pos, "grammemes": grammemes, "form": form})

        return {"word": req.word, "lemma": word_lower, "pos": pos_found, "forms": forms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/suffix_stats")
def api_suffix_stats(req: SuffixStatsRequest):
    try:
        db_path = os.path.join(str(PARENT_DIR), 'data', 'language', 'suffix_model.sqlite3')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pos, grammemes, count, total, probability "
            "FROM suffix_stats WHERE suffix = ? ORDER BY probability DESC LIMIT 20",
            (req.suffix,)
        )
        rows = cursor.fetchall()
        conn.close()

        stats = []
        total_count = 0
        for pos, grammemes, count, total, probability in rows:
            stats.append({
                "pos": pos,
                "grammemes": grammemes,
                "count": count,
                "total": total,
                "probability": probability
            })
            total_count += count

        return {"suffix": req.suffix, "stats": stats, "total_count": total_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/morphemes_catalog")
def api_morphemes_catalog():
    try:
        import yaml
        morph_dir = os.path.join(str(PARENT_DIR), 'neuromorph', 'data', 'reference', 'morphemes')
        result = {}
        for name in ('suffixes', 'prefixes', 'endings'):
            filepath = os.path.join(morph_dir, f'{name}.yaml')
            with open(filepath, 'r', encoding='utf-8') as f:
                result[name] = yaml.safe_load(f)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


import re as _re
_CLEAN_MORPHEME_RE = _re.compile(r'^[а-яёА-ЯЁ\-]+$')

def _is_clean_morpheme(s: str) -> bool:
    """Check if a morpheme string is a real morpheme (not a grammatical note)."""
    if not s or len(s) > 20:
        return False
    return bool(_CLEAN_MORPHEME_RE.match(s))

_wikt_suffixes = None
def _get_wikt_suffixes() -> set:
    """Load Wiktionary suffix set for validation."""
    global _wikt_suffixes
    if _wikt_suffixes is not None:
        return _wikt_suffixes
    wikt_path = os.path.join(str(PARENT_DIR), 'morphtransformations', 'data', 'wiktionary_morphemes.json')
    if not os.path.exists(wikt_path):
        # Try alternate path
        wikt_path = os.path.join(os.path.dirname(__file__), 'data', 'wiktionary_morphemes.json')
    suffixes = set()
    if os.path.exists(wikt_path):
        with open(wikt_path, 'r', encoding='utf-8') as f:
            wikt = json.load(f)
        for morph in wikt.get('suffixes', {}):
            m = morph.lstrip('-').lower().strip()
            if m:
                suffixes.add(m)
    _wikt_suffixes = suffixes
    return _wikt_suffixes

_morpheme_index = None
def _get_morpheme_index():
    """Build inverted index: (type, morpheme) -> list of words.
    
    Reads from word_morphemes table (has ё-restored lemmas).
    """
    global _morpheme_index
    if _morpheme_index is not None:
        return _morpheme_index

    conn = sqlite3.connect(_PARADIGMS_DB)
    c = conn.cursor()
    
    # Map DB mtype to index type
    type_map = {'PREFIX': 'prefix', 'ROOT': 'root', 'SUFFIX': 'suffix', 'ENDING': 'ending', 'LINK': 'link'}
    
    c.execute("""
        SELECT DISTINCT lemma, morpheme, mtype FROM word_morphemes 
        WHERE source = 'tikhonov'
    """)
    
    idx = {}  # (type, morpheme) -> [word1, word2, ...]
    for lemma, morpheme, mtype in c.fetchall():
        t = type_map.get(mtype, 'suffix')
        if t == 'link':
            continue  # Don't index interfixes
        idx.setdefault((t, morpheme), []).append(lemma)
    
    # Deduplicate word lists
    for key in idx:
        idx[key] = sorted(set(idx[key]))
    
    conn.close()
    _morpheme_index = idx
    return _morpheme_index


@app.post("/api/morpheme_search")
def api_morpheme_search(req: MorphemeSearchRequest):
    try:
        idx = _get_morpheme_index()
        morpheme = req.morpheme.strip().lower()
        if morpheme == '*':
            morpheme = ''
        mtype = req.morpheme_type.strip().lower()

        if not morpheme:
            # Empty search: show all unique morphemes per type
            if mtype == 'any':
                results = {}
                for t in ('prefix', 'suffix', 'ending', 'root', 'compound_root'):
                    morphemes = sorted(set(m for (tp, m) in idx if tp == t))
                    if morphemes:
                        results[t] = [{"value": m, "count": len(idx.get((t, m), []))} for m in morphemes]
                total = sum(len(v) for v in results.values())
                flat_results = []
                for t, ms in results.items():
                    flat_results.extend(ms)
                results = flat_results
            else:
                morphemes = sorted(set(m for (tp, m) in idx if tp == mtype))
                results = []
                for m in morphemes:
                    words = idx.get((mtype, m), [])
                    results.append({"value": m, "count": len(words), "example": words[0] if words else ""})
                results.sort(key=lambda x: x["value"])
                total = len(results)
            
            # Pagination
            page = max(1, req.page)
            page_size = req.page_size if req.page_size > 0 else 0
            pagination = None
            if page_size > 0 and total > page_size:
                total_pages = (total + page_size - 1) // page_size
                offset = (page - 1) * page_size
                page_results = results[offset:offset + page_size]
                pagination = {
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                    "shown": len(page_results)
                }
                results = page_results

            return {
                "morpheme": "",
                "type": mtype,
                "results": results,
                "total": total,
                "only_unique": True,
                "pagination": pagination
            }

        # Helper: lookup with ё↔е fallback
        def _lookup(t, m):
            words = idx.get((t, m), [])
            if not words:
                # Try ё↔е fallback
                alt = m.replace('ё', 'е') if 'ё' in m else m.replace('е', 'ё')
                if alt != m:
                    words = idx.get((t, alt), [])
            return words

        # Collect all words from results, then batch-lookup decompositions
        def _add_decomp(results_dict):
            all_words = []
            for words in results_dict.values():
                all_words.extend(words)
            if not all_words:
                return {}
            conn2 = sqlite3.connect(_PARADIGMS_DB)
            c2 = conn2.cursor()
            decomp = {}
            source_rank = {}  # lemma -> best source rank (tikhonov=0, algorithmic=1, unknown=2)
            rank_map = {'tikhonov': 0, 'algorithmic': 1, 'unknown': 2}
            batch_size = 900
            for i in range(0, len(all_words), batch_size):
                batch = all_words[i:i+batch_size]
                placeholders = ','.join('?' * len(batch))
                c2.execute(f"""
                    SELECT lemma, morpheme, mtype, source FROM word_morphemes
                    WHERE lemma IN ({placeholders})
                    ORDER BY lemma, position
                """, batch)
                for lemma, morph, mt, src in c2.fetchall():
                    r = rank_map.get(src, 2)
                    cur_rank = source_rank.get(lemma, 99)
                    if r < cur_rank:
                        # Better source found, replace
                        decomp[lemma] = [[mt, morph]]
                        source_rank[lemma] = r
                    elif r == cur_rank:
                        decomp.setdefault(lemma, []).append([mt, morph])
            conn2.close()
            # Deduplicate: keep only first POS decomposition per lemma
            for lemma in decomp:
                seen = set()
                unique = []
                for pair in decomp[lemma]:
                    key = (pair[0], pair[1])
                    if key not in seen:
                        seen.add(key)
                        unique.append(pair)
                decomp[lemma] = unique
            return decomp

        page = req.page
        page_size = req.page_size if req.page_size > 0 else 0

        if mtype == 'any':
            # Search across all types
            results = {}
            for t in ('prefix', 'suffix', 'ending', 'root'):
                words = _lookup(t, morpheme)
                if words:
                    results[t] = words
            total = sum(len(v) for v in results.values())
            
            # Paginate the combined word list
            pagination = None
            if page_size > 0 and total > page_size:
                total_pages = (total + page_size - 1) // page_size
                offset = (page - 1) * page_size
                # Flatten, paginate, then reconstruct
                all_words = []
                for t in ('prefix', 'suffix', 'ending', 'root'):
                    for w in results.get(t, []):
                        all_words.append((t, w))
                page_words = all_words[offset:offset + page_size]
                results = {}
                for t, w in page_words:
                    results.setdefault(t, []).append(w)
                pagination = {"page": page, "page_size": page_size, "total_pages": total_pages, "shown": len(page_words)}
            
            # Decomp for current page only (always fits)
            decomp = _add_decomp(results)
            resp = {
                "morpheme": morpheme,
                "type": "any",
                "results": results,
                "total": total,
                "decomp": decomp
            }
            if pagination:
                resp["pagination"] = pagination
            return resp
        else:
            words = _lookup(mtype, morpheme)
            total = len(words)
            
            # Paginate
            pagination = None
            if page_size > 0 and total > page_size:
                total_pages = (total + page_size - 1) // page_size
                offset = (page - 1) * page_size
                page_words = words[offset:offset + page_size]
                pagination = {"page": page, "page_size": page_size, "total_pages": total_pages, "shown": len(page_words)}
                words = page_words
            
            results = {mtype: words} if words else {}
            # Decomp for current page only (always fits)
            decomp = _add_decomp(results)
            resp = {
                "morpheme": morpheme,
                "type": mtype,
                "results": results,
                "total": total,
                "decomp": decomp
            }
            if pagination:
                resp["pagination"] = pagination
            return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: Ending search via OpenCorpora paradigms (3.1M forms)
# ---------------------------------------------------------------------------
_PARADIGMS_DB = os.path.join(str(PARENT_DIR), 'data', 'language', 'ru_paradigms.sqlite3')

POS_LABELS = {
    "NOUN": "Существительное", "ADJF": "Прилагательное", "ADJS": "Кр. прилагательное",
    "VERB": "Глагол", "INFN": "Инфинитив", "PRTF": "Причастие", "PRTS": "Кр. причастие",
    "GRND": "Деепричастие", "ADVB": "Наречие", "COMP": "Сравнительная",
    "NUMR": "Числительное", "NPRO": "Местоимение", "PRED": "Предикатив",
    "PREP": "Предлог", "CONJ": "Союз", "PRCL": "Частица", "INTJ": "Междометие",
}

class EndingSearchRequest(BaseModel):
    ending: str
    pos: str = "any"
    search_type: str = "ending"  # prefix, suffix, root, ending, any
    word_filter: str = ""  # additional substring filter on form
    limit: int = 5000  # max results per POS group (0 = unlimited)
    page: int = 1  # 1-based page number
    page_size: int = 5000  # items per page (0 = all)
    uncovered_only: bool = False

def _fetch_ending_words(req: EndingSearchRequest, c):
    ending = req.ending.lower().strip()
    pos = req.pos.upper().strip()
    stype = req.search_type.lower().strip()
    word_filter = getattr(req, 'word_filter', '').lower().strip()

    if stype == 'root':
        # For root search: use word_morphemes (same as main search)
        query = """SELECT DISTINCT lemma FROM word_morphemes
            WHERE mtype='ROOT' AND morpheme=? AND source != 'unknown'
            AND lemma IN (SELECT DISTINCT lemma FROM paradigms)"""
        params = [ending]
        if pos != 'ANY':
            query += " AND pos = ?"
            params.append(pos)
        if word_filter:
            query += " AND lemma LIKE ?"
            params.append(f'%{word_filter}%')
        query += " ORDER BY lemma"
        c.execute(query, params)
        return [(r[0],) for r in c.fetchall()]

    if stype == 'prefix':
        pattern = f'{ending}%'
    elif stype == 'suffix' or stype == 'ending':
        pattern = f'%{ending}'
    else:
        pattern = f'%{ending}%'

    query = "SELECT DISTINCT lemma FROM paradigms WHERE form LIKE ?"
    params = [pattern]

    if pos != 'ANY':
        query += " AND pos = ?"
        params.append(pos)
    
    if word_filter:
        query += " AND lemma LIKE ?"
        params.append(f'%{word_filter}%')

    query += " ORDER BY lemma"
    c.execute(query, params)
    return c.fetchall()

@app.post("/api/ending_export")
def api_ending_export(req: EndingSearchRequest):
    try:
        conn = sqlite3.connect(_PARADIGMS_DB)
        c = conn.cursor()
        
        all_rows = _fetch_ending_words(req, c)
        all_lemmas = [r[0] for r in all_rows]  # r[0] = lemma
        unique_words = list(dict.fromkeys(all_lemmas))
        
        # Decompose only to find uncovered
        from engine.hdc.morpheme_algebra import MorphemeAlgebra
        _ma = MorphemeAlgebra()
        
        results = []
        if getattr(req, 'uncovered_only', False):
            for w in unique_words:
                decomp = _ma.decompose(w)
                if len(decomp) == 1 and decomp[0][0] == "ROOT":
                    results.append(w)
        else:
            results = unique_words
            
        conn.close()
        return {"words": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AlgorithmicRequest(BaseModel):
    morpheme_type: str = "any"  # prefix, suffix, root, ending, any
    page: int = 1
    page_size: int = 200

@app.post("/api/algorithmic_registry")
def api_algorithmic_registry(req: AlgorithmicRequest):
    """Return unique morphemes of a given type from algorithmic source — same format as Tikhonov/OC registry."""
    try:
        conn = sqlite3.connect(_PARADIGMS_DB)
        c = conn.cursor()
        
        type_map = {'prefix': 'PREFIX', 'suffix': 'SUFFIX', 'root': 'ROOT', 'ending': 'ENDING'}
        target = type_map.get(req.morpheme_type, 'SUFFIX')
        
        c.execute("""
            SELECT morpheme, COUNT(DISTINCT lemma) as cnt
            FROM word_morphemes
            WHERE mtype = ? AND source = 'algorithmic'
            GROUP BY morpheme
            ORDER BY morpheme
        """, (target,))
        results = [{"value": r[0], "count": r[1]} for r in c.fetchall()]
        
        # Example words for download
        if req.page_size == 0:
            for item in results:
                c.execute("SELECT lemma FROM word_morphemes WHERE mtype = ? AND morpheme = ? AND source = 'algorithmic' LIMIT 1",
                          (target, item["value"]))
                row = c.fetchone()
                item["example"] = row[0] if row else ""
        
        conn.close()
        return {
            "ending": "*",
            "only_unique": True,
            "type": target,
            "total": len(results),
            "results": results,
            "source": "algorithmic"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@app.post("/api/algorithmic_words")
def api_algorithmic_words(req: AlgorithmicRequest):
    """Return words decomposed by the algorithmic method from word_morphemes table."""
    try:
        conn = sqlite3.connect(_PARADIGMS_DB)
        c = conn.cursor()
        
        # Get unique lemmas with algorithmic source
        mtype_filter = ""
        params = ['algorithmic']
        if req.morpheme_type != 'any':
            type_map = {'prefix': 'PREFIX', 'suffix': 'SUFFIX', 'root': 'ROOT', 'ending': 'ENDING'}
            target = type_map.get(req.morpheme_type, 'ROOT')
            mtype_filter = " AND lemma IN (SELECT DISTINCT lemma FROM word_morphemes WHERE mtype = ? AND source = 'algorithmic')"
            params.append(target)
        
        # Count total
        c.execute(f"SELECT COUNT(DISTINCT lemma) FROM word_morphemes WHERE source = ?{mtype_filter}", params)
        total = c.fetchone()[0]
        
        # Get paginated lemmas
        page = max(1, req.page)
        page_size = req.page_size if req.page_size > 0 else total
        offset = (page - 1) * page_size
        
        c.execute(f"""
            SELECT DISTINCT lemma FROM word_morphemes 
            WHERE source = ?{mtype_filter}
            ORDER BY lemma
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])
        lemmas = [r[0] for r in c.fetchall()]
        
        # Get full decomposition for each lemma (pick one POS to avoid duplicates)
        results = []
        for lemma in lemmas:
            c.execute("""
                SELECT morpheme, mtype, position FROM word_morphemes 
                WHERE lemma = ? AND source = 'algorithmic'
                  AND pos = (SELECT MIN(pos) FROM word_morphemes WHERE lemma = ? AND source = 'algorithmic')
                ORDER BY position
            """, (lemma, lemma))
            morphemes = [{"value": r[0], "type": r[1]} for r in c.fetchall()]
            results.append({"lemma": lemma, "morphemes": morphemes})
        
        conn.close()
        
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        return {
            "results": results,
            "total": total,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "shown": len(results)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ending_search")
def api_ending_search(req: EndingSearchRequest):
    try:
        conn = sqlite3.connect(_PARADIGMS_DB)
        c = conn.cursor()
        
        ending = req.ending.lower().strip()
        stype = req.search_type.lower().strip()
        pos = req.pos.upper().strip()
        is_empty_search = (not ending or ending == '*')
        
        # Curated prefix classification (academic morphology: Грамота, Ефремова, Wiktionary)
        _VALID_PREFIXES = {
            # Core Russian prefixes
            'за', 'пере', 'по', 'на', 'о', 'вы', 'про', 'у', 'с', 'от', 'при', 'под',
            'об', 'рас', 'раз', 'до', 'не', 'из', 'ис', 'со', 'вз', 'без', 'бес',
            'вс', 'пре', 'пред', 'над', 'низ', 'меж', 'ни', 'обо', 'ото', 'подо', 'разо',
            'нис', 'изо', 'сверх', 'надо', 'пра', 'взо', 'черес', 'через', 'чрез',
            # Foreign prefixes
            'анти', 'де', 'дез', 'ре', 'экс', 'дис', 'контр', 'интер', 'суб',
            'транс', 'пост', 'пан', 'ультра', 'экстра', 'супер', 'архи',
        }
        _PREFIX_LIKE = {'су', 'па', 'в', 'между', 'около'}  # historical/ambiguous
        # Excluded: пер, ра, бе, межд, экстр, ни, пр — not valid prefixes
        
        if is_empty_search and stype != 'any':
            m_type_map = {'prefix': 'PREFIX', 'suffix': 'SUFFIX', 'root': 'ROOT', 'ending': 'ENDING'}
            target_type = m_type_map.get(stype, 'PREFIX')
            
            # Use word_morphemes table (indexed, fast)
            if target_type == 'PREFIX':
                all_valid = _VALID_PREFIXES | _PREFIX_LIKE
                placeholders = ','.join(['?' for _ in all_valid])
                c.execute(f"""
                    SELECT morpheme, COUNT(DISTINCT lemma) as cnt 
                    FROM word_morphemes 
                    WHERE mtype = 'PREFIX' AND morpheme IN ({placeholders}) AND source != 'unknown'
                    GROUP BY morpheme ORDER BY morpheme
                """, list(all_valid))
                unique_list = [{"value": r[0], "count": r[1]} for r in c.fetchall()]
            else:
                # For root: count lemmas that exist in BOTH word_morphemes AND paradigms
                # (matching the actual search behavior which joins the two tables)
                if target_type == 'ROOT':
                    c.execute("""
                        SELECT wm.morpheme, COUNT(DISTINCT wm.lemma) as cnt
                        FROM word_morphemes wm
                        WHERE wm.mtype = 'ROOT' AND wm.source != 'unknown'
                          AND wm.lemma IN (SELECT DISTINCT lemma FROM paradigms)
                        GROUP BY wm.morpheme ORDER BY wm.morpheme
                    """)
                    unique_list = [{"value": r[0], "count": r[1]} for r in c.fetchall()]
                else:
                    # For suffix/ending: use precomputed lemma counts
                    unique_list = []
                    try:
                        c.execute("""
                            SELECT morpheme, form_count FROM morpheme_form_counts 
                            WHERE mtype = ? AND stype = ?
                            ORDER BY morpheme
                        """, (target_type, stype))
                        unique_list = [{"value": r[0], "count": r[1]} for r in c.fetchall()]
                    except sqlite3.OperationalError:
                        pass
                    
                    if not unique_list:
                        # Table empty or missing — fallback to lemma count from word_morphemes
                        c.execute("""
                            SELECT morpheme, COUNT(DISTINCT lemma) as cnt 
                            FROM word_morphemes 
                            WHERE mtype = ? AND source != 'unknown'
                            GROUP BY morpheme ORDER BY morpheme
                        """, (target_type,))
                        unique_list = [{"value": r[0], "count": r[1]} for r in c.fetchall()]
            
            # Add example words only for downloads (slow: 1 query per morpheme)
            if req.page_size == 0:
                for item in unique_list:
                    c.execute("SELECT lemma FROM word_morphemes WHERE mtype = ? AND morpheme = ? AND source != 'unknown' LIMIT 1",
                              (target_type, item["value"]))
                    row = c.fetchone()
                    item["example"] = row[0] if row else ""
            real_total = len(unique_list)
            conn.close()
            return {
                "ending": ending,
                "only_unique": True,
                "type": target_type,
                "results": unique_list,
                "total": real_total
            }
        if stype == 'prefix':
            pattern = f'{ending}%'
        elif stype == 'suffix' or stype == 'ending':
            pattern = f'%{ending}'
        else:
            pattern = f'%{ending}%'
        word_filter = req.word_filter.strip().lower()

        # Build additional word filter clause
        extra_where = ""
        extra_params = []
        if word_filter:
            extra_where = " AND lemma LIKE ?"
            extra_params = [f'%{word_filter}%']

        # Pagination params
        page = max(1, req.page)
        page_size = req.page_size if req.page_size > 0 else 0  # 0 = unlimited

        # For ROOT search on OpenCorpora: use word_morphemes for both POS and lemma list,
        # paradigms only as existence filter. This gives each lemma exactly ONE POS.
        if stype == 'root':
            lemma_where = ""
            lemma_params = []
            if word_filter:
                lemma_where = " AND wm.lemma LIKE ?"
                lemma_params = [f'%{word_filter}%']

            if pos == "ANY" or pos == "":
                # Fetch all (pos, lemma) pairs — need dedup since same lemma has multiple POS
                c.execute(f"""
                    SELECT DISTINCT wm.pos, wm.lemma FROM word_morphemes wm
                    WHERE wm.mtype='ROOT' AND wm.morpheme=? AND wm.source != 'unknown'
                      AND wm.lemma IN (SELECT DISTINCT lemma FROM paradigms){lemma_where}
                    ORDER BY wm.pos, wm.lemma
                """, (ending, *lemma_params))
                rows = c.fetchall()
                
                # Deduplicate: each lemma → one POS (highest priority)
                _POS_PRI = {
                    'NOUN': 0, 'ADJF': 1, 'VERB': 2, 'INFN': 3, 'ADVB': 4,
                    'ADJS': 5, 'PRTF': 6, 'PRTS': 7, 'GRND': 8, 'COMP': 9,
                    'NUMR': 10, 'NPRO': 11, 'PRED': 12, 'PREP': 13,
                    'CONJ': 14, 'PRCL': 15, 'INTJ': 16,
                }
                best_pos = {}
                for p, lemma in rows:
                    pri = _POS_PRI.get(p, 99)
                    if lemma not in best_pos or pri < best_pos[lemma][0]:
                        best_pos[lemma] = (pri, p)
                
                # Group -ся/-сь reflexive variants with base forms
                reflexive_bases = set()
                to_remove = set()
                for lemma in list(best_pos.keys()):
                    if lemma.endswith('ся') or lemma.endswith('сь'):
                        base = lemma[:-2]
                        if base in best_pos:
                            reflexive_bases.add(base)
                            to_remove.add(lemma)
                for lemma in to_remove:
                    del best_pos[lemma]
                
                results = {}
                for lemma in sorted(best_pos, key=lambda l: (best_pos[l][0], l)):
                    p = best_pos[lemma][1]
                    display = f"{lemma}(ся)" if lemma in reflexive_bases else lemma
                    results.setdefault(p, []).append(display)
                
                pos_counts = {p: len(v) for p, v in results.items()}
                total = sum(pos_counts.values())
                
                # Apply pagination after dedup
                if page_size > 0:
                    offset = (page - 1) * page_size
                    all_lemmas = []
                    for p in sorted(results.keys(), key=lambda x: _POS_PRI.get(x, 99)):
                        for lemma in results[p]:
                            all_lemmas.append((p, lemma))
                    page_slice = all_lemmas[offset:offset + page_size]
                    results = {}
                    for p, lemma in page_slice:
                        results.setdefault(p, []).append(lemma)
            else:
                c.execute(f"""
                    SELECT COUNT(DISTINCT wm.lemma) FROM word_morphemes wm
                    WHERE wm.mtype='ROOT' AND wm.morpheme=? AND wm.pos=? AND wm.source != 'unknown'
                      AND wm.lemma IN (SELECT DISTINCT lemma FROM paradigms){lemma_where}
                """, (ending, pos, *lemma_params))
                total = c.fetchone()[0]
                pos_counts = {pos: total}

                if page_size > 0:
                    offset = (page - 1) * page_size
                    c.execute(f"""
                        SELECT DISTINCT wm.lemma FROM word_morphemes wm
                        WHERE wm.mtype='ROOT' AND wm.morpheme=? AND wm.pos=? AND wm.source != 'unknown'
                          AND wm.lemma IN (SELECT DISTINCT lemma FROM paradigms){lemma_where}
                        ORDER BY wm.lemma LIMIT ? OFFSET ?
                    """, (ending, pos, *lemma_params, page_size, offset))
                else:
                    c.execute(f"""
                        SELECT DISTINCT wm.lemma FROM word_morphemes wm
                        WHERE wm.mtype='ROOT' AND wm.morpheme=? AND wm.pos=? AND wm.source != 'unknown'
                          AND wm.lemma IN (SELECT DISTINCT lemma FROM paradigms){lemma_where}
                        ORDER BY wm.lemma
                    """, (ending, pos, *lemma_params))
                rows = c.fetchall()
                lemmas = [r[0] for r in rows]
                results = {pos: lemmas}
        elif pos == "ANY" or pos == "":
            # Fetch all unique (pos, lemma) pairs — need dedup since paradigms has form-level POS
            if page_size > 0:
                # Fetch slightly more to account for dedup reducing count
                offset = (page - 1) * page_size
                c.execute(
                    f"SELECT DISTINCT pos, lemma FROM paradigms WHERE form LIKE ?{extra_where} ORDER BY pos, lemma",
                    (pattern, *extra_params)
                )
            else:
                c.execute(
                    f"SELECT DISTINCT pos, lemma FROM paradigms WHERE form LIKE ?{extra_where} ORDER BY pos, lemma",
                    (pattern, *extra_params)
                )
            rows = c.fetchall()
            
            # Deduplicate: each lemma → one POS (highest priority)
            _POS_PRI = {
                'NOUN': 0, 'ADJF': 1, 'VERB': 2, 'INFN': 3, 'ADVB': 4,
                'ADJS': 5, 'PRTF': 6, 'PRTS': 7, 'GRND': 8, 'COMP': 9,
                'NUMR': 10, 'NPRO': 11, 'PRED': 12, 'PREP': 13,
                'CONJ': 14, 'PRCL': 15, 'INTJ': 16,
            }
            best_pos = {}
            for p, lemma in rows:
                pri = _POS_PRI.get(p, 99)
                if lemma not in best_pos or pri < best_pos[lemma][0]:
                    best_pos[lemma] = (pri, p)
            
            # Group -ся/-сь reflexive variants with base forms
            reflexive_bases = set()
            to_remove = set()
            for lemma in list(best_pos.keys()):
                if lemma.endswith('ся') or lemma.endswith('сь'):
                    base = lemma[:-2]
                    if base in best_pos:
                        reflexive_bases.add(base)
                        to_remove.add(lemma)
            for lemma in to_remove:
                del best_pos[lemma]
            
            results = {}
            for lemma in sorted(best_pos, key=lambda l: (best_pos[l][0], l)):
                p = best_pos[lemma][1]
                display = f"{lemma}(ся)" if lemma in reflexive_bases else lemma
                results.setdefault(p, []).append(display)
            
            pos_counts = {p: len(v) for p, v in results.items()}
            total = sum(pos_counts.values())
            
            # Apply pagination after dedup
            if page_size > 0:
                all_lemmas = []
                for p in sorted(results.keys(), key=lambda x: _POS_PRI.get(x, 99)):
                    for lemma in results[p]:
                        all_lemmas.append((p, lemma))
                page_slice = all_lemmas[offset:offset + page_size]
                results = {}
                for p, lemma in page_slice:
                    results.setdefault(p, []).append(lemma)
        else:
            # Single POS — count total (by unique lemma)
            c.execute(
                f"SELECT COUNT(DISTINCT lemma) FROM paradigms WHERE pos = ? AND form LIKE ?{extra_where}",
                (pos, pattern, *extra_params)
            )
            total = c.fetchone()[0]
            pos_counts = {pos: total}

            # Fetch paginated lemmas
            if page_size > 0:
                offset = (page - 1) * page_size
                c.execute(
                    f"SELECT DISTINCT lemma FROM paradigms WHERE pos = ? AND form LIKE ?{extra_where} ORDER BY lemma LIMIT ? OFFSET ?",
                    (pos, pattern, *extra_params, page_size, offset)
                )
            else:
                c.execute(
                    f"SELECT DISTINCT lemma FROM paradigms WHERE pos = ? AND form LIKE ?{extra_where} ORDER BY lemma",
                    (pos, pattern, *extra_params)
                )
            rows = c.fetchall()
            lemmas = [r[0] for r in rows]
            results = {pos: lemmas}

        # Calculate pagination metadata
        shown = sum(len(v) for v in results.values())
        total_pages = ((total + page_size - 1) // page_size) if page_size > 0 else 1
        all_words_page = []
        for wlist in results.values():
            for w in wlist:
                # Strip (ся) suffix for decomposition lookup
                all_words_page.append(w[:-4] if w.endswith('(ся)') else w)

        # Calculate global uncovered count if total is not too huge
        # Skip for root searches — LIKE '%пуск%' matches substrings, not root morphemes
        uncovered_only_total = -1
        if stype != 'root' and total < 20000:
            # We need to fetch ALL distinct forms for this query to check decomposition
            c.execute(
                f"SELECT DISTINCT form FROM paradigms WHERE form LIKE ?{extra_where}",
                (pattern, *extra_params)
            )
            all_forms_global = [r[0] for r in c.fetchall()]
            
            from engine.hdc.morpheme_algebra import MorphemeAlgebra
            _ma = MorphemeAlgebra()
            
            uncovered_count = 0
            for w in all_forms_global:
                decomp_res = _ma.decompose(w)
                if len(decomp_res) == 1 and decomp_res[0][0] == "ROOT":
                    uncovered_count += 1
            uncovered_only_total = uncovered_count

        decomp = {}
        if stype == 'root' and all_words_page:
            # For root search: use word_morphemes for decomposition (correct Tikhonov data)
            # Take only one POS per lemma to avoid duplicate morpheme rows
            batch_size = 900
            for i in range(0, len(all_words_page), batch_size):
                batch = all_words_page[i:i+batch_size]
                placeholders = ','.join('?' * len(batch))
                # First, find one POS per lemma (MIN gives alphabetically first)
                c.execute(f"""
                    SELECT lemma, MIN(pos) as pos FROM word_morphemes
                    WHERE lemma IN ({placeholders}) AND source != 'unknown'
                    GROUP BY lemma
                """, batch)
                lemma_pos = {r[0]: r[1] for r in c.fetchall()}
                
                # Now fetch morphemes for each lemma with its selected POS
                for lemma, pos_val in lemma_pos.items():
                    c.execute("""
                        SELECT mtype, morpheme FROM word_morphemes
                        WHERE lemma = ? AND pos = ? AND source != 'unknown'
                        ORDER BY position
                    """, (lemma, pos_val))
                    parts = [[r[0], r[1]] for r in c.fetchall()]
                    if parts:
                        decomp[lemma] = parts
        elif all_words_page:
            tikh = _get_tikhonov_data().get('dictionary', {})

            # Batch lookup: form → lemma
            batch_size = 900
            form_to_lemma = {}
            for i in range(0, len(all_words_page), batch_size):
                batch = all_words_page[i:i+batch_size]
                placeholders = ','.join('?' * len(batch))
                c.execute(f'SELECT form, lemma FROM paradigms WHERE form IN ({placeholders})', batch)
                for form, lemma in c.fetchall():
                    if form not in form_to_lemma:
                        form_to_lemma[form] = lemma
                    elif lemma in tikh and form_to_lemma[form] not in tikh:
                        form_to_lemma[form] = lemma
                    elif lemma in tikh and form_to_lemma[form] in tikh and len(lemma) < len(form_to_lemma[form]):
                        form_to_lemma[form] = lemma

            _ENDING_PROBES = ('', 'ий', 'ый', 'ой', 'ая', 'ое', 'ать', 'ить', 'еть', 'ь', 'е', 'о', 'а')

            def _find_entry(word, tikh):
                """Find Tikhonov entry for word, trying common endings."""
                entry = tikh.get(word)
                if entry:
                    return entry
                for suf in _ENDING_PROBES:
                    if suf and (entry := tikh.get(word + suf)):
                        return entry
                return None

            def _decompose_entry(entry):
                """Build morpheme parts list from a Tikhonov entry (without ending)."""
                parts = []
                for p in entry.get('prefixes', []):
                    pc = p.rstrip('0123456789').strip()
                    if pc and not any(c in pc for c in '( ,;:<>=+'):
                        parts.append(['PREFIX', pc])
                root = entry.get('root', '').rstrip('0123456789').strip()
                parts.append(['ROOT', root])
                for s in entry.get('suffixes', []):
                    s_clean = s.rstrip('0123456789').strip()
                    if s_clean and not any(c in s_clean for c in '( ,;:<>=+') and len(s_clean) < 8:
                        parts.append(['SUFFIX', s_clean])
                return parts

            def _try_compound(lemma, tikh, depth=0):
                """Split compound word: hyphens, joining vowels, recursive."""
                if depth > 3:
                    return None

                # --- 1. Hyphenated words: балочно-стоечный ---
                if '-' in lemma:
                    hyp_parts = lemma.split('-')
                    all_parts = []
                    any_found = False
                    for idx, part in enumerate(hyp_parts):
                        entry = _find_entry(part, tikh)
                        if entry:
                            all_parts.extend(_decompose_entry(entry))
                            any_found = True
                        else:
                            # Try compound decomposition on this part too
                            sub = _try_compound(part, tikh, depth + 1)
                            if sub:
                                all_parts.extend(sub)
                                any_found = True
                            else:
                                all_parts.append(['ROOT', part])
                        if idx < len(hyp_parts) - 1:
                            all_parts.append(['LINK', '-'])
                    return all_parts if any_found else None

                # --- 2. Joining vowel split ---
                best = None
                for jv in ('о', 'е', 'и'):
                    for i in range(3, len(lemma) - 3):
                        if lemma[i] != jv:
                            continue
                        left = lemma[:i]
                        right_after = lemma[i+1:]
                        right_with = lemma[i:]

                        if len(right_after) < 3:
                            continue

                        # Try right WITH the vowel (со-держать, по-глощать)
                        re_full = _find_entry(right_with, tikh)
                        if re_full:
                            rp = _decompose_entry(re_full)
                            rp_stem = ''.join(v for _, v in rp)
                            if right_with.startswith(rp_stem):
                                le = _find_entry(left, tikh)
                                lp = _decompose_entry(le) if le else [['ROOT', left]]
                                score = (2 if le else 1) + 2
                                if not best or score > best[0]:
                                    best = (score, lp + rp)

                        # Try right WITHOUT the vowel (лес-о-образующий)
                        re = _find_entry(right_after, tikh)
                        if re:
                            rp = _decompose_entry(re)
                            rp_stem = ''.join(v for _, v in rp)
                            if right_after.startswith(rp_stem):
                                le = _find_entry(left, tikh)
                                lp = _decompose_entry(le) if le else [['ROOT', left]]
                                score = (2 if le else 1) + 1
                                if not best or score > best[0]:
                                    best = (score, lp + [['LINK', jv]] + rp)
                        elif len(right_after) > 5:
                            # Recurse on right part (девяносто-четырёх-летний)
                            sub = _try_compound(right_after, tikh, depth + 1)
                            if sub:
                                has_real_root = any(t == 'ROOT' and len(v) >= 3 for t, v in sub)
                                if has_real_root:
                                    le = _find_entry(left, tikh)
                                    lp = _decompose_entry(le) if le else [['ROOT', left]]
                                    score = (2 if le else 1) + 1
                                    if not best or score > best[0]:
                                        best = (score, lp + [['LINK', jv]] + sub)

                # --- 3. Known compound first-parts (авиа+парашютный) ---
                _COMPOUND_HEADS = (
                    'авиа', 'авто', 'аэро', 'вело', 'мото', 'фото', 'радио',
                    'видео', 'аудио', 'гидро', 'электро', 'нефте', 'газо',
                    'теле', 'кино', 'микро', 'макро', 'мега', 'нано', 'био',
                    'гео', 'нейро', 'психо', 'турбо', 'стерео', 'метео',
                )
                for head in _COMPOUND_HEADS:
                    if lemma.startswith(head) and len(lemma) > len(head) + 2:
                        rest = lemma[len(head):]
                        re = _find_entry(rest, tikh)
                        if re:
                            rp = _decompose_entry(re)
                            rp_stem = ''.join(v for _, v in rp)
                            if rest.startswith(rp_stem):  # validate
                                score = 3
                                if not best or score > best[0]:
                                    best = (score, [['ROOT', head]] + rp)
                        if not best or best[0] < 3:
                            sub = _try_compound(rest, tikh, depth + 1)
                            if sub:
                                score = 2
                                if not best or score > best[0]:
                                    best = (score, [['ROOT', head]] + sub)

                # --- 4. Morphological prefix stripping (по+нечаянный) ---
                _MORPH_PREFIXES = (
                    'пере', 'пред', 'анти', 'сверх', 'меж', 'между',
                    'при', 'пре', 'без', 'бес', 'рас', 'раз',
                    'над', 'под', 'воз', 'вос', 'обо', 'ото',
                    'по', 'на', 'за', 'от', 'об', 'до', 'вы', 'из', 'ис', 'не',
                    'у', 'с', 'в',
                )
                for pref in _MORPH_PREFIXES:
                    if lemma.startswith(pref) and len(lemma) > len(pref) + 2:
                        rest = lemma[len(pref):]
                        re = _find_entry(rest, tikh)
                        if re:
                            rp = _decompose_entry(re)
                            rp_stem = ''.join(v for _, v in rp)
                            if rest.startswith(rp_stem):  # validate
                                score = 2
                                if not best or score > best[0]:
                                    best = (score, [['PREFIX', pref]] + rp)
                        else:
                            # Try double prefix: из+маяться → ис+паясничать
                            sub = _try_compound(rest, tikh, depth + 1)
                            if sub:
                                score = 1
                                if not best or score > best[0]:
                                    best = (score, [['PREFIX', pref]] + sub)

                return best[1] if best else None

            # --- Strategy 5: Suffix-based fallback for words NOT in Tikhonov ---
            _KNOWN_SUFFIXES = (
                # Longest first for greedy matching
                'тельн', 'ическ', 'ческ', 'ивист', 'ирова', 'изова',
                'ирующ', 'изующ',
                'альн', 'ельн', 'ильн', 'ульн', 'овочн', 'ёвочн',
                'ическ', 'оват', 'еват',
                'онн', 'енн', 'анн', 'инн',
                'ист', 'лив', 'чив',
                'ова', 'ева',
                'ующ', 'ющ', 'ущ', 'ащ', 'ящ',  # active participle
                'ск', 'ов', 'ев', 'ан', 'ян', 'ен',
                'ем', 'им',  # passive participle
                'нн',  # past passive participle
                'н', 'к', 'л',
            )
            _KNOWN_ENDINGS = ('ая', 'ой', 'ый', 'ий', 'ое', 'ые', 'ых', 'ом', 'ым',
                              'ей', 'ых', 'ую', 'юю', 'его', 'ому', 'ыми', 'ими',
                              'ат', 'ят', 'ут', 'ют', 'ет', 'ёт', 'ит',
                              'ал', 'ял', 'ил', 'ел', 'ол', 'ул',
                              'ала', 'яла', 'ила', 'ела', 'ула',
                              'али', 'яли', 'или', 'ели', 'ули',
                              'ало', 'яло', 'ило', 'ело', 'уло',
                              'ю', 'у', 'а', 'о', 'и', 'е', 'ы', '')
            _FALLBACK_PREFIXES = (
                'пере', 'пред', 'анти', 'сверх', 'меж', 'между',
                'при', 'пре', 'без', 'бес', 'рас', 'раз',
                'над', 'под', 'воз', 'вос', 'обо', 'ото',
                'про', 'пре',
                'по', 'на', 'за', 'от', 'об', 'до', 'вы', 'из', 'ис', 'не',
                'у', 'с', 'в',
            )

            def _suffix_fallback(word):
                """Decompose by suffix pattern recognition (no dictionary needed)."""
                w = word.lower()
                parts = []

                # Strip prefix(es)
                for pref in _FALLBACK_PREFIXES:
                    if w.startswith(pref) and len(w) > len(pref) + 3:
                        parts.append(['PREFIX', pref])
                        w = w[len(pref):]
                        break  # one prefix max for fallback

                # Strip ending
                end_found = ''
                for end in _KNOWN_ENDINGS:
                    if end and w.endswith(end) and len(w) > len(end) + 2:
                        end_found = end
                        w = w[:-len(end)]
                        break

                # Find suffix
                suf_found = ''
                for suf in _KNOWN_SUFFIXES:
                    if w.endswith(suf) and len(w) > len(suf) + 1:
                        suf_found = suf
                        w = w[:-len(suf)]
                        break

                if not w:
                    return None

                parts.append(['ROOT', w])
                if suf_found:
                    parts.append(['SUFFIX', suf_found])
                if end_found:
                    parts.append(['ENDING', end_found])

                return parts

            for word in all_words_page:
                # --- Numeric forms: 1950-ые, 100-летний, 2-й ---
                if any(ch.isdigit() for ch in word):
                    if '-' in word:
                        num_part, alpha_part = word.split('-', 1)
                        if num_part and alpha_part:
                            # Try decomposing the alpha part
                            alpha_lemma = form_to_lemma.get(alpha_part)
                            alpha_entry = tikh.get(alpha_lemma) if alpha_lemma else None
                            if alpha_entry:
                                ap = _decompose_entry(alpha_entry)
                                ap_stem = ''.join(v for _, v in ap)
                                if alpha_part.startswith(ap_stem):
                                    end_p = alpha_part[len(ap_stem):]
                                    if end_p:
                                        ap.append(['ENDING', end_p])
                                    decomp[word] = [['ROOT', num_part], ['LINK', '-']] + ap
                                else:
                                    decomp[word] = [['ROOT', num_part], ['LINK', '-'], ['ENDING', alpha_part]]
                            else:
                                # Simple: number + ending
                                decomp[word] = [['ROOT', num_part], ['LINK', '-'], ['ENDING', alpha_part]]
                    else:
                        # Pure numeric or mixed: treat entire word as ROOT
                        decomp[word] = [['ROOT', word]]
                    continue

                lemma = form_to_lemma.get(word)
                if not lemma:
                    continue
                entry = tikh.get(lemma)
                if entry:
                    parts = _decompose_entry(entry)
                    # Validate: stem must prefix lemma (catches corrupt entries)
                    stem_check = ''.join(v for _, v in parts)
                    if not lemma.startswith(stem_check):
                        parts = _try_compound(lemma, tikh)
                else:
                    parts = _try_compound(lemma, tikh)
                if not parts:
                    # Fallback: suffix-based decomposition
                    fb = _suffix_fallback(lemma)
                    if fb:
                        stem = ''.join(v for t, v in fb if v and t != 'ENDING')
                        if word.startswith(stem):
                            end_part = word[len(stem):]
                            fb_no_end = [p for p in fb if p[0] != 'ENDING']
                            if end_part:
                                fb_no_end.append(['ENDING', end_part])
                            decomp[word] = fb_no_end
                        else:
                            # Try verb trim on fallback too
                            matched = False
                            for vs in ('ться', 'ть', 'ся', 'сь'):
                                if stem.endswith(vs):
                                    tr = stem[:-len(vs)]
                                    if tr and word.startswith(tr):
                                        fb2 = [p for p in fb if p[0] != 'ENDING']
                                        fb2_trimmed = []
                                        rem = tr
                                        for t, v in fb2:
                                            if rem.startswith(v):
                                                fb2_trimmed.append([t, v])
                                                rem = rem[len(v):]
                                            elif rem:
                                                fb2_trimmed.append([t, rem])
                                                rem = ''
                                        ep = word[len(tr):]
                                        if ep:
                                            fb2_trimmed.append(['ENDING', ep])
                                        decomp[word] = fb2_trimmed
                                        matched = True
                                        break
                            if not matched:
                                # Try fallback on the WORD form itself
                                fb_w = _suffix_fallback(word)
                                if fb_w:
                                    stem_w = ''.join(v for t, v in fb_w if v and t != 'ENDING')
                                    if word.startswith(stem_w):
                                        end_w = word[len(stem_w):]
                                        fb_w_no_end = [p for p in fb_w if p[0] != 'ENDING']
                                        if end_w:
                                            fb_w_no_end.append(['ENDING', end_w])
                                        decomp[word] = fb_w_no_end
                    continue
                stem = ''.join(v for _, v in parts)
                if word.startswith(stem):
                    end_part = word[len(stem):]
                    if end_part:
                        parts.append(['ENDING', end_part])
                    decomp[word] = parts
                else:
                    # Try trimming verb suffixes from stem (ться, ть, ся, сь)
                    for verb_suf in ('ться', 'ть', 'ся', 'сь'):
                        if stem.endswith(verb_suf):
                            trimmed = stem[:-len(verb_suf)]
                            if trimmed and word.startswith(trimmed):
                                trimmed_parts = []
                                remaining = trimmed
                                for t, v in parts:
                                    if remaining.startswith(v):
                                        trimmed_parts.append([t, v])
                                        remaining = remaining[len(v):]
                                    elif remaining:
                                        take = remaining
                                        trimmed_parts.append([t, take])
                                        remaining = ''
                                end_part = word[len(trimmed):]
                                if end_part:
                                    trimmed_parts.append(['ENDING', end_part])
                                decomp[word] = trimmed_parts
                                break
                    else:
                        # Try short-form adjective: stem ends in нн but word has single н
                        if stem.endswith('нн') and word.startswith(stem[:-1]):
                            trimmed = stem[:-1]
                            parts_adj = []
                            rem = trimmed
                            for t, v in parts:
                                if rem.startswith(v):
                                    parts_adj.append([t, v])
                                    rem = rem[len(v):]
                                elif rem:
                                    parts_adj.append([t, rem])
                                    rem = ''
                            ep = word[len(trimmed):]
                            if ep:
                                parts_adj.append(['ENDING', ep])
                            decomp[word] = parts_adj
                        elif word not in decomp:
                            # Last resort: suffix fallback on word form itself
                            fb_w = _suffix_fallback(word)
                            if fb_w:
                                stem_w = ''.join(v for t, v in fb_w if v and t != 'ENDING')
                                if word.startswith(stem_w):
                                    end_w = word[len(stem_w):]
                                    fb_w_no_end = [p for p in fb_w if p[0] != 'ENDING']
                                    if end_w:
                                        fb_w_no_end.append(['ENDING', end_w])
                                    decomp[word] = fb_w_no_end

            # --- Filtering by morpheme type (if requested) ---
            # Skip for root search: word_morphemes already guarantees correct root
            if stype in ('prefix', 'suffix'):
                filtered_results = {}
                filtered_decomp = {}
                m_type_map = {'prefix': 'PREFIX', 'suffix': 'SUFFIX', 'root': 'ROOT'}
                target_type = m_type_map[stype]
                
                for p, words in results.items():
                    kept_words = []
                    for w in words:
                        # Strip (ся) for decomp lookup
                        lookup_key = w[:-4] if w.endswith('(ся)') else w
                        parts = decomp.get(lookup_key) or decomp.get(w)
                        if parts:
                            # Match if any part of target_type contains the searched string
                            # or if target_type is PREFIX and word starts with ending
                            match = False
                            for t, v in parts:
                                if t == target_type and ending in v.lower():
                                    match = True
                                    break
                            if match:
                                kept_words.append(w)
                                filtered_decomp[lookup_key] = parts
                    if kept_words:
                        filtered_results[p] = kept_words
                
                results = filtered_results
                decomp = filtered_decomp
                # Update total, pos_counts, pagination to reflect filtered results
                pos_counts = {p: len(v) for p, v in results.items()}
                total = sum(pos_counts.values())
                shown = total
                total_pages = 1  # After post-hoc filtering, pagination doesn't make sense

        conn.close()
        
        # Collect morpheme stats from the batch
        morpheme_stats = {"PREFIX": {}, "ROOT": {}, "SUFFIX": {}, "ENDING": {}, "LINK": {}}
        companion_roots = {}  # Second roots in compound words
        for parts in decomp.values():
            for t, v in parts:
                if t in morpheme_stats:
                    # For root search: separate the searched root from companion roots
                    if stype == 'root' and t == 'ROOT' and ending not in v.lower():
                        companion_roots[v] = companion_roots.get(v, 0) + 1
                    else:
                        morpheme_stats[t][v] = morpheme_stats[t].get(v, 0) + 1
        if companion_roots:
            morpheme_stats["COMPANION_ROOT"] = companion_roots
                    
        unique_words = list(dict.fromkeys(all_words_page))  # deduplicate preserving order
        decomp_count = len(decomp)
        uncovered = [w for w in unique_words if w not in decomp]
        # For root search: compute uncovered from decomp results (all words are on page)
        if stype == 'root' and uncovered_only_total == -1:
            uncovered_only_total = len(uncovered)
        return {
            "ending": ending,
            "pos": pos if pos != "ANY" else "any",
            "results": results,
            "total": total,
            "pos_labels": POS_LABELS,
            "pos_counts": pos_counts,
            "decomp": decomp,
            "morpheme_stats": morpheme_stats,
            "coverage": {
                "decomposed": decomp_count,
                "total_shown": len(unique_words),
                "pct": round(100 * decomp_count / len(unique_words), 1) if unique_words else 0
            },
            "uncovered": uncovered,
            "uncovered_only_total": uncovered_only_total,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "shown": shown,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Mount static folder
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
