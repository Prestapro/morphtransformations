"""
dialogue_parser.py
Universal Russian dialogue parser.
Formats: DRAMA (play), PROSE_EM (em-dash prose), PROSE_Q (quoted prose), MIXED.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TextFormat(Enum):
    DRAMA    = "drama"
    PROSE_EM = "prose_em"
    PROSE_Q  = "prose_q"
    MIXED    = "mixed"


class LineType(Enum):
    SPEAKER   = "speaker"
    SPEECH    = "speech"
    STAGE_DIR = "stage_dir"
    AUTHOR    = "author"
    EMPTY     = "empty"


@dataclass
class ParsedLine:
    raw: str
    line_type: LineType
    speaker: Optional[str] = None
    text: Optional[str] = None


@dataclass
class Turn:
    """One character's speech block — the core unit of analysis."""
    turn_id: int
    speaker: str
    lines: list[str]      = field(default_factory=list)
    stage_dirs: list[str] = field(default_factory=list)
    author_words: list[str] = field(default_factory=list)
    source_format: TextFormat = TextFormat.DRAMA
    highlight: bool = False

    def full_speech(self) -> str:
        return " ".join(self.lines)

    def __repr__(self) -> str:
        preview = self.full_speech()[:60]
        return (f"Turn(id={self.turn_id}, speaker={self.speaker!r}, "
                f"lines={len(self.lines)}, stage_dirs={len(self.stage_dirs)}, "
                f"preview={preview!r})")


# ── Регулярные выражения ──────────────────────────────────────

_ATTR_VERBS = re.compile(
    r"\b(сказал[аи]?|говорил[аи]?|ответил[аи]?|спросил[аи]?|"
    r"воскликнул[аи]?|прошептал[аи]?|крикнул[аи]?|произнёс|произнесла|"
    r"добавил[аи]?|заметил[аи]?|перебил[аи]?|пробормотал[аи]?|"
    r"усмехнул(?:ся|ась)|вздохнул[аи]?|продолжал[аи]?|подумал[аи]?|"
    r"процедил[аи]?|буркнул[аи]?)\b",
    re.IGNORECASE,
)

_STAGE_VERBS = re.compile(
    r"\b(уходит|уходят|входит|входят|садится|садятся|встаёт|встают|"
    r"останавливает|берёт|подходит|отходит|смеётся|смеются|плачет|плачут|"
    r"кланяется|кланяются|целует|обнимает|обнимаются|читает|пишет|"
    r"открывает|закрывает|выходит|выходят|появляется|исчезает|"
    r"смотрит|смотрят|молчит|молчат|указывает|машет)\b",
    re.IGNORECASE,
)

_EM_DASH_START = re.compile(r"^[—–-]\s*")

_NOT_NAMES = frozenset({
    "Боже", "Господи", "Нет", "Да", "Ах", "Так",
    "Вот", "Всё", "Там", "Тут", "Ведь", "Уже",
})


# ── Детекция формата ─────────────────────────────────────────

def detect_format(text: str) -> TextFormat:
    lines = [l.strip() for l in text.splitlines() if l.strip()][:50]
    drama  = sum(1 for l in lines if _is_drama_speaker_candidate(l))
    em     = sum(1 for l in lines if l.startswith("—") or l.startswith("– "))
    quote  = sum(1 for l in lines if l.startswith("«") or l.startswith('"'))
    if drama >= 2 and drama > em:
        return TextFormat.DRAMA
    if em > quote:
        return TextFormat.PROSE_EM
    if quote > 0:
        return TextFormat.PROSE_Q
    return TextFormat.MIXED


# ── Детекторы строк ──────────────────────────────────────────

def _is_drama_speaker_candidate(line: str,
                                 known_speakers: Optional[set] = None) -> bool:
    """
    Строка — имя персонажа в пьесе.
    Критерии: 1-3 токена, все с заглавной,
    нет знаков препинания внутри (кроме точки в конце).
    """
    s = line.strip().rstrip(".")
    if not s:
        return False
    bad = set(",;!?—–«»\"\u201c\u201d()…:")
    if any(c in bad for c in s):
        return False
    tokens = s.split()
    if not (1 <= len(tokens) <= 3):
        return False
    if not all(t[0].isupper() for t in tokens if t):
        return False
    if known_speakers is not None and tokens[0] not in known_speakers:
        return False
    return True


def _is_stage_direction(line: str) -> bool:
    """
    Ремарка: в скобках ИЛИ короткая строка с глаголом действия.
    ВАЖНО: не закрывает Turn — добавляется внутрь него.
    """
    s = line.strip()
    if not s:
        return False
    if (s.startswith("(") and s.endswith(")")) or \
       (s.startswith("[") and s.endswith("]")):
        return True
    if (len(s.split()) <= 7
            and not _EM_DASH_START.match(s)
            and not s.startswith("«")
            and not s.startswith('"')
            and _STAGE_VERBS.search(s)):
        return True
    return False


def _extract_speaker(text: str) -> Optional[str]:
    """Извлекает имя из слов автора: 'ответила Маша' → 'Маша'."""
    m = re.search(r"\b([А-ЯЁ][а-яё]{2,})\b", text)
    if m and m.group(1) not in _NOT_NAMES:
        return m.group(1)
    return None


# ── Классификаторы по формату ────────────────────────────────

def classify_drama_line(line: str,
                         known: Optional[set] = None) -> ParsedLine:
    s = line.strip()
    if not s:
        return ParsedLine(raw=line, line_type=LineType.EMPTY)
    if _is_stage_direction(s):
        return ParsedLine(raw=line, line_type=LineType.STAGE_DIR, text=s)
    if _is_drama_speaker_candidate(s, known):
        return ParsedLine(raw=line, line_type=LineType.SPEAKER,
                          speaker=s.rstrip("."))
    return ParsedLine(raw=line, line_type=LineType.SPEECH, text=s)


def classify_prose_em_line(line: str) -> ParsedLine:
    """
    Проза с тире. Все паттерны по Розенталю §195:
      — Речь.
      — Речь, — сказал он.
      — Начало, — сказал он, — продолжение.
      — Начало! — воскликнул он. — Продолжение.
    """
    s = line.strip()
    if not s:
        return ParsedLine(raw=line, line_type=LineType.EMPTY)
    if _is_stage_direction(s):
        return ParsedLine(raw=line, line_type=LineType.STAGE_DIR, text=s)

    if _EM_DASH_START.match(s):
        content = _EM_DASH_START.sub("", s).strip()

        # Ищем разрыв: «текст, — сказал он»
        split1 = re.split(r"[,!?]\s*[—–]\s*", content, maxsplit=1)
        if len(split1) == 2 and _ATTR_VERBS.search(split1[1]):
            speech_a   = split1[0].strip()
            author_etc = split1[1]
            split2     = re.split(r"[.,]\s*[—–]\s*", author_etc, maxsplit=1)
            author_txt = split2[0].strip()
            cont       = split2[1].strip() if len(split2) > 1 else ""
            speech     = (speech_a + (" " + cont if cont else "")).strip()
            return ParsedLine(raw=line, line_type=LineType.SPEECH,
                              text=speech,
                              speaker=_extract_speaker(author_txt)
                              if _ATTR_VERBS.search(author_txt) else None)

        return ParsedLine(raw=line, line_type=LineType.SPEECH, text=content)

    return ParsedLine(raw=line, line_type=LineType.AUTHOR, text=s)


def classify_prose_q_line(line: str) -> ParsedLine:
    """Проза с кавычками «» или ""."""
    s = line.strip()
    if not s:
        return ParsedLine(raw=line, line_type=LineType.EMPTY)
    if _is_stage_direction(s):
        return ParsedLine(raw=line, line_type=LineType.STAGE_DIR, text=s)

    m = re.match(r'^[«\u201c"](.+?)[»\u201d"]\s*[—–,]?\s*(.*)', s, re.DOTALL)
    if m:
        speech  = m.group(1).strip()
        rest    = m.group(2).strip()
        speaker = _extract_speaker(rest) if _ATTR_VERBS.search(rest) else None
        return ParsedLine(raw=line, line_type=LineType.SPEECH,
                          text=speech, speaker=speaker)

    if _EM_DASH_START.match(s):
        return classify_prose_em_line(line)

    return ParsedLine(raw=line, line_type=LineType.AUTHOR, text=s)


# ── Главный парсер ───────────────────────────────────────────

class DialogueParser:
    """
    Универсальный парсер диалогов для русских текстов.

    Параметры
    ---------
    known_speakers : set[str]
        Имена персонажей (опционально, повышает точность детекции).

    Пример
    ------
    parser = DialogueParser(known_speakers={"Фамусов", "Лиза", "Чацкий"})
    turns  = parser.parse(text)

    for turn in turns:
        # Морфемный анализ на уровне Turn, не строки:
        score = morpheme_analyzer(turn.full_speech())
        turn.highlight = score > threshold
    """

    def __init__(self, known_speakers: Optional[set[str]] = None):
        self.known_speakers = known_speakers or set()

    def parse(self, text: str) -> list[Turn]:
        fmt    = detect_format(text)
        lines  = text.splitlines()
        parsed = self._classify_lines(lines, fmt)
        return self._build_turns(parsed, fmt)

    def _classify_lines(self, lines, fmt):
        ks = self.known_speakers or None
        classify = {
            TextFormat.DRAMA:    lambda l: classify_drama_line(l, ks),
            TextFormat.PROSE_EM: classify_prose_em_line,
            TextFormat.PROSE_Q:  classify_prose_q_line,
            TextFormat.MIXED:    lambda l: self._classify_mixed(l, ks),
        }[fmt]
        return [classify(l) for l in lines]

    def _classify_mixed(self, line, known=None):
        s = line.strip()
        if not s:
            return ParsedLine(raw=line, line_type=LineType.EMPTY)
        if _is_stage_direction(s):
            return ParsedLine(raw=line, line_type=LineType.STAGE_DIR, text=s)
        if _is_drama_speaker_candidate(s, known):
            return ParsedLine(raw=line, line_type=LineType.SPEAKER,
                              speaker=s.rstrip("."))
        if _EM_DASH_START.match(s):
            return classify_prose_em_line(line)
        if s.startswith("«") or s.startswith('"'):
            return classify_prose_q_line(line)
        return ParsedLine(raw=line, line_type=LineType.AUTHOR, text=s)

    def _build_turns(self, parsed: list[ParsedLine], fmt: TextFormat) -> list[Turn]:
        """
        Ключевое правило закрытия Turn
        ──────────────────────────────
        Turn закрывается ТОЛЬКО при встрече нового SPEAKER.
        Пустые строки и ремарки Turn НЕ закрывают — остаются внутри.
        """
        turns: list[Turn] = []
        current: Optional[Turn] = None
        ctr = 0

        def new_turn(spk: str) -> Turn:
            nonlocal ctr
            t = Turn(turn_id=ctr, speaker=spk, source_format=fmt)
            ctr += 1
            return t

        for pl in parsed:
            if pl.line_type == LineType.EMPTY:
                continue                           # ← НЕ закрываем Turn

            elif pl.line_type == LineType.SPEAKER:
                if current:
                    turns.append(current)
                current = new_turn(pl.speaker)

            elif pl.line_type == LineType.STAGE_DIR:
                if current is None:
                    current = new_turn("narrator")
                current.stage_dirs.append(pl.text or pl.raw.strip())

            elif pl.line_type == LineType.SPEECH:
                spk = pl.speaker
                if spk and spk != (current.speaker if current else None):
                    if current:
                        turns.append(current)
                    current = new_turn(spk)
                elif current is None:
                    current = new_turn("UNKNOWN")
                current.lines.append(pl.text or pl.raw.strip())

            elif pl.line_type == LineType.AUTHOR:
                if current:
                    current.author_words.append(pl.text or pl.raw.strip())

        if current:
            turns.append(current)
        return turns


# ── Точка входа ──────────────────────────────────────────────

if __name__ == "__main__":
    TESTS = {
        "Пьеса (Горе от ума)": (
            {"Фамусов", "Лиза", "Чацкий", "Софья"},
            """Лиза
Ах! барин!
Фамусов
Барин, да.

(Останавливает часовую музыку.)
Ведь экая шалунья ты девчонка.
Не мог придумать я, что это за беда!
То флейта слышится, то будто фортопьяно;
Для Софьи слишком было б рано?..
Лиза
Нет, сударь, я... лишь невзначай...
Фамусов
Вот то-то невзначай, за вами примечай;
Так верно с умыслом."""
        ),
        "Проза с тире": (
            set(),
            """— Ты куда идёшь? — спросил Иван.
— Домой, — ответила Маша. — А ты?
— Я ещё побуду здесь."""
        ),
        "Проза с кавычками": (
            set(),
            """«Всё кончено», — подумал он.
— Подожди! — крикнула она вслед."""
        ),
    }

    for title, (speakers, text) in TESTS.items():
        print(f"\n{'='*55}\n{title}\n{'='*55}")
        parser = DialogueParser(known_speakers=speakers)
        for t in parser.parse(text):
            print(f"\n  [Turn #{t.turn_id}] {t.speaker}")
            for l in t.lines:
                print(f"    речь:    {l}")
            for s in t.stage_dirs:
                print(f"    ремарка: {s}")
            for a in t.author_words:
                print(f"    автор:   {a}")
