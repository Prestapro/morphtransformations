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

    Tikhonov stores everything after the first root as 'suffixes',
    including second roots of compound words. We split them:
    - 'suffix' = verified against Wiktionary (559 real suffixes)
    - 'compound_root' = second stems of compound words
    """
    global _morpheme_index
    if _morpheme_index is not None:
        return _morpheme_index

    data = _get_tikhonov_data()
    dictionary = data.get('dictionary', {})
    wikt_suf = _get_wikt_suffixes()

    idx = {}  # (type, morpheme) -> [word1, word2, ...]
    for word, entry in dictionary.items():
        # Prefixes
        for p in entry.get('prefixes', []):
            p_clean = p.strip().lower()
            if _is_clean_morpheme(p_clean):
                idx.setdefault(('prefix', p_clean), []).append(word)
        # Suffixes — split into real suffixes vs compound roots
        for s in entry.get('suffixes', []):
            s_clean = s.strip().lower()
            if _is_clean_morpheme(s_clean):
                if s_clean in wikt_suf or len(s_clean) <= 3:
                    idx.setdefault(('suffix', s_clean), []).append(word)
                else:
                    idx.setdefault(('compound_root', s_clean), []).append(word)
        # Ending
        ending = entry.get('ending', '').strip().lower()
        if _is_clean_morpheme(ending):
            idx.setdefault(('ending', ending), []).append(word)
        # Root
        root = entry.get('root', '').strip().lower()
        if _is_clean_morpheme(root):
            idx.setdefault(('root', root), []).append(word)

    _morpheme_index = idx
    return _morpheme_index


@app.post("/api/morpheme_search")
def api_morpheme_search(req: MorphemeSearchRequest):
    try:
        idx = _get_morpheme_index()
        morpheme = req.morpheme.strip().lower()
        mtype = req.morpheme_type.strip().lower()

        if not morpheme:
            # Empty search: show all unique morphemes per type
            if mtype == 'any':
                results = {}
                for t in ('prefix', 'suffix', 'ending', 'root', 'compound_root'):
                    morphemes = sorted(set(m for (tp, m) in idx if tp == t))
                    if morphemes:
                        results[t] = morphemes
                total = sum(len(v) for v in results.values())
            else:
                morphemes = sorted(set(m for (tp, m) in idx if tp == mtype))
                results = {mtype: morphemes} if morphemes else {}
                total = len(morphemes)
            return {
                "morpheme": "",
                "type": mtype,
                "results": results,
                "total": total
            }

        if mtype == 'any':
            # Search across all types
            results = {}
            for t in ('prefix', 'suffix', 'ending', 'root', 'compound_root'):
                words = idx.get((t, morpheme), [])
                if words:
                    results[t] = words
            total = sum(len(v) for v in results.values())
            return {
                "morpheme": morpheme,
                "type": "any",
                "results": results,
                "total": total
            }
        else:
            words = idx.get((mtype, morpheme), [])
            return {
                "morpheme": morpheme,
                "type": mtype,
                "results": {mtype: words} if words else {},
                "total": len(words)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# API: Ending search via OpenCorpora paradigms (3.1M forms)
# ---------------------------------------------------------------------------
class EndingSearchRequest(BaseModel):
    ending: str
    pos: str = "any"
    search_type: str = "ending"  # prefix, suffix, ending, any
    word_filter: str = ""  # additional substring filter on form
    limit: int = 5000  # max results per POS group

_PARADIGMS_DB = os.path.join(str(PARENT_DIR), 'data', 'language', 'ru_paradigms.sqlite3')

POS_LABELS = {
    "NOUN": "Существительное", "ADJF": "Прилагательное", "ADJS": "Кр. прилагательное",
    "VERB": "Глагол", "INFN": "Инфинитив", "PRTF": "Причастие", "PRTS": "Кр. причастие",
    "GRND": "Деепричастие", "ADVB": "Наречие", "COMP": "Сравнительная",
    "NUMR": "Числительное", "NPRO": "Местоимение", "PRED": "Предикатив",
    "PREP": "Предлог", "CONJ": "Союз", "PRCL": "Частица", "INTJ": "Междометие",
}

@app.post("/api/ending_search")
async def api_ending_search(req: EndingSearchRequest):
    ending = req.ending.strip().lower()
    pos = req.pos.strip().upper()
    stype = req.search_type.strip().lower()
    if len(ending) > 10:
        raise HTTPException(status_code=400, detail="ending too long")

    try:
        conn = sqlite3.connect(_PARADIGMS_DB)
        c = conn.cursor()
        if stype == 'prefix':
            pattern = f'{ending}%'
        elif stype == 'suffix' or stype == 'ending':
            pattern = f'%{ending}'
        else:
            pattern = f'%{ending}%'
        limit = req.limit
        if limit <= 0:
            limit = None  # unlimited
        else:
            limit = min(limit, 50000)  # cap at 50K per POS
        word_filter = req.word_filter.strip().lower()

        # Build additional word filter clause
        extra_where = ""
        extra_params = []
        if word_filter:
            extra_where = " AND form LIKE ?"
            extra_params = [f'%{word_filter}%']
            limit = min(limit, 50000)  # allow more with filter

        if pos == "ANY" or pos == "":
            c.execute(
                f"SELECT pos, form FROM (SELECT DISTINCT pos, form FROM paradigms WHERE form LIKE ?{extra_where}) ORDER BY pos, form",
                (pattern, *extra_params)
            )
            rows = c.fetchall()
            results = {}
            for p, form in rows:
                results.setdefault(p, []).append(form)
            total = 0
            for p in results:
                total += len(results[p])
                results[p] = sorted(results[p])[:limit]
        else:
            c.execute(
                f"SELECT DISTINCT form FROM paradigms WHERE pos = ? AND form LIKE ?{extra_where} ORDER BY form",
                (pos, pattern, *extra_params)
            )
            rows = c.fetchall()
            forms = [r[0] for r in rows]
            total = len(forms)
            results = {pos: forms[:limit]}

        # --- Morpheme decomposition for displayed words ---
        all_words = []
        for wlist in results.values():
            all_words.extend(wlist)

        decomp = {}
        if all_words:
            tikh = _get_tikhonov_data().get('dictionary', {})

            # Batch lookup: form → lemma
            batch_size = 900
            form_to_lemma = {}
            for i in range(0, len(all_words), batch_size):
                batch = all_words[i:i+batch_size]
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
                    pc = p.rstrip('0123456789')
                    if pc and ' ' not in pc:
                        parts.append(['PREFIX', pc])
                root = entry.get('root', '').rstrip('0123456789')
                parts.append(['ROOT', root])
                for s in entry.get('suffixes', []):
                    s_clean = s.rstrip('0123456789')
                    if s_clean and '(' not in s_clean and ' ' not in s_clean and len(s_clean) < 8:
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

            for word in all_words:
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

        conn.close()
        unique_words = list(dict.fromkeys(all_words))  # deduplicate preserving order
        decomp_count = len(decomp)
        uncovered = [w for w in unique_words if w not in decomp]
        return {
            "ending": ending,
            "pos": pos if pos != "ANY" else "any",
            "results": results,
            "total": total,
            "pos_labels": POS_LABELS,
            "decomp": decomp,
            "coverage": {
                "decomposed": decomp_count,
                "total_shown": len(unique_words),
                "pct": round(100 * decomp_count / len(unique_words), 1) if unique_words else 0
            },
            "uncovered": uncovered
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Mount static folder
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
