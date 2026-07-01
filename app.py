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


# Mount static folder
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
