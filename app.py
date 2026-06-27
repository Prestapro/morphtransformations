import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent directory to sys.path so we can import engine
PARENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PARENT_DIR))

try:
    from engine.language.inflector import inflect as db_inflect, agree_adjective, _get_conn
except ImportError:
    # Fallback/stub if not running inside the logos workspace
    db_inflect = None
    agree_adjective = None
    _get_conn = None

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

VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")

OFFICIAL_WHITELIST = {
    "учительница", "писательница", "актриса", "спортсменка", 
    "студентка", "космонавтка", "докладчица", "участница", 
    "помощница", "руководительница"
}

HOMONYM_OVERRIDES = {
    "пилотка": "головной убор",
    "электричка": "пригородный поезд",
    "совка": "бабочка / совок",
    "овсянка": "крупа / птица"
}

class InflectRequest(BaseModel):
    word: str
    grammemes: str

class FeminitiveRequest(BaseModel):
    word: str
    style: str  # 'colloquial' or 'official'

def check_homonym_collision(word: str) -> str | None:
    """Check if the candidate word already exists as an inanimate object."""
    if word in HOMONYM_OVERRIDES:
        return HOMONYM_OVERRIDES[word]
        
    if _get_conn is not None:
        try:
            conn = _get_conn()
            # Query if word exists with non-anim grammemes or inanim pos
            rows = conn.execute(
                "SELECT grammemes FROM paradigms WHERE form = ? LIMIT 5",
                (word.lower(),)
            ).fetchall()
            for (gram,) in rows:
                if "inan" in gram:
                    return "существительное (неодуш.)"
        except Exception:
            pass
    return None

def generate_feminitive_rule(masc: str) -> tuple[str, str, str]:
    """Apply morphotactic rules to generate feminitive and return the rule explanation."""
    masc_lower = masc.lower().strip()
    
    if masc_lower.endswith("ец"):
        # Rule 1: ец ending
        char_before = masc_lower[-3] if len(masc_lower) >= 3 else ""
        if char_before in VOWELS:
            fem = masc_lower[:-2] + "ейка"
            rule = "Основа на 'ец' предваряется гласной -> суффикс меняется на 'ейка' (европеец -> европейка)"
        else:
            fem = masc_lower[:-2] + "анка" if masc_lower.endswith("анец") else masc_lower[:-2] + "ка"
            rule = "Основа на 'ец' предваряется согласной -> суффикс меняется на 'ка' (американец -> американка)"
        return fem, rule, "ец"
        
    if masc_lower.endswith("тель"):
        fem = masc_lower[:-4] + "тельница"
        rule = "Основа на 'тель' -> суффикс меняется на 'тельница' (учитель -> учительница)"
        return fem, rule, "тель"
        
    if masc_lower.endswith("арь"):
        fem = masc_lower[:-3] + "арка"
        rule = "Основа на 'арь' -> суффикс меняется на 'арка' (пекарь -> пекарка)"
        return fem, rule, "арь"
        
    if masc_lower.endswith("ик"):
        fem = masc_lower[:-2] + "ица"
        rule = "Основа на 'ик' -> суффикс меняется на 'ица' (художник -> художница)"
        return fem, rule, "ик"
        
    # Default consonant ending
    fem = masc_lower + "ка"
    rule = "Основа оканчивается на согласную -> прибавление суффикса 'ка' (блогер -> блогерка)"
    return fem, rule, "consonant"

@app.post("/api/inflect")
def api_inflect(req: InflectRequest):
    if db_inflect is None:
        raise HTTPException(status_code=500, detail="Database inflector is unavailable.")
        
    try:
        gram_set = set(g.strip() for g in req.grammemes.split(",") if g.strip())
        res = db_inflect(req.word, gram_set)
        if res:
            return {"word": req.word, "result": res}
        return {"word": req.word, "result": req.word, "warning": "Слово не найдено в парадигмах"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feminitive")
def api_feminitive(req: FeminitiveRequest):
    word = req.word.strip()
    if not word:
        return {"error": "Пустое слово"}
        
    fem_candidate, rule_desc, trigger_suf = generate_feminitive_rule(word)
    
    # Capitalization match
    if word[0].isupper():
        fem_candidate = fem_candidate.capitalize()
        
    # Check style register
    blocked = False
    message = "Словосочетание семантически корректно."
    
    if req.style == "official":
        if fem_candidate.lower() not in OFFICIAL_WHITELIST:
            blocked = True
            message = f"В официально-деловом стиле феминитив '{fem_candidate}' заблокирован. Используйте мужской род: '{word}'."
            
    # Check homonym collision
    collision = check_homonym_collision(fem_candidate)
    if collision:
        blocked = True
        message = f"Словообразовательное столкновение! Феминитив '{fem_candidate}' заблокирован, так как это слово уже занято: {collision}."

    # LCP Split calculation
    i = 0
    while i < min(len(word), len(fem_candidate)) and word[i] == fem_candidate[i]:
        i += 1
    stem = word[:i]
    masc_suf = word[i:]
    fem_suf = fem_candidate[i:]

    return {
        "masculine": word,
        "feminitive": fem_candidate if not blocked else word,
        "stem": stem,
        "masc_suffix": masc_suf,
        "fem_suffix": fem_suf,
        "rule": rule_desc,
        "style": req.style,
        "blocked": blocked,
        "message": message,
        "collision": collision is not None
    }

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

# Mount static folder
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
