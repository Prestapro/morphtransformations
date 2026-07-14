"""Evidence-backed document structure extraction for Spectrum."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class BoundaryStatus(str, Enum):
    CONFIRMED = 'confirmed'
    UNKNOWN = 'unknown'
    REJECTED = 'rejected'


@dataclass(frozen=True)
class ChapterBoundary:
    title: str
    char_range: tuple[int, int]
    status: BoundaryStatus
    confidence: float
    evidence: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            'kind': 'chapter',
            'title': self.title,
            'char_range': list(self.char_range),
            'status': self.status.value,
            'confidence': self.confidence,
            'evidence': list(self.evidence),
        }


_ROMAN_NUMERAL = re.compile(r'^[IVXLCDMХХ]{1,8}$', re.IGNORECASE)
_NUMBERED_HEADING = re.compile(r'^\D{1,40}\s+(?:\d+|[IVXLCDMХХ]{1,8})$', re.IGNORECASE)


def _roman_value(value: str) -> int | None:
    value = value.upper().replace('Х', 'X')
    if not re.fullmatch(r'[IVXLCDM]{1,8}', value):
        return None
    numerals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    previous = 0
    for char in reversed(value):
        number = numerals[char]
        total += -number if number < previous else number
        previous = max(previous, number)
    return total


def _is_candidate(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or stripped[-1:] in '.!?…,:;':
        return False
    if stripped.startswith(('(', '[', '—', '–', '-')):
        return False
    words = stripped.split()
    return len(words) <= 8


def _shape(line: str) -> str:
    stripped = line.strip()
    if _ROMAN_NUMERAL.fullmatch(stripped):
        return 'roman_numeral'
    if _NUMBERED_HEADING.fullmatch(stripped):
        return 'numbered_heading'
    words = stripped.split()
    if words and all(word[:1].isupper() for word in words):
        return f'title_case:{len(words)}'
    return f'short_line:{len(words)}'


def detect_chapter_boundaries(text: str) -> list[ChapterBoundary]:
    """Return chapter boundaries with ternary status and structural evidence.

    The detector does not infer that a narrative scene boundary is a chapter.
    A heading is confirmed only by an explicit numeric form or a repeated
    document-local heading shape; isolated short lines stay unknown.
    """
    candidates = []
    offset = 0
    nonempty_line_index = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        start = offset + (len(line) - len(line.lstrip()))
        if _is_candidate(line):
            candidates.append((stripped, start, start + len(stripped), _shape(stripped), nonempty_line_index))
        if stripped:
            nonempty_line_index += 1
        offset += len(line)

    # A leading title/author/dedication block is metadata, not chapter structure.
    first_structural = next(
        (item[4] for item in candidates if item[3] in {'roman_numeral', 'numbered_heading'}),
        None,
    )
    if first_structural is not None:
        candidates = [item for item in candidates if item[4] >= first_structural]

    shape_counts: dict[str, int] = {}
    for _, _, _, shape, _ in candidates:
        shape_counts[shape] = shape_counts.get(shape, 0) + 1

    roman_values = [_roman_value(title) for title, _, _, shape, _ in candidates if shape == 'roman_numeral']
    sequential_roman = len(roman_values) >= 2 and all(
        current == previous + 1 for previous, current in zip(roman_values, roman_values[1:])
    )

    boundaries = []
    for title, start, end, shape, _ in candidates:
        explicit = shape == 'numbered_heading' or (shape == 'roman_numeral' and sequential_roman)
        repeated = shape_counts[shape] >= 2 and shape != 'roman_numeral'
        if shape == 'roman_numeral' and not sequential_roman:
            continue
        if explicit or repeated:
            evidence = ['short_isolated_line', shape]
            if repeated or (shape == 'roman_numeral' and sequential_roman):
                evidence.append('repeated_heading_template')
            boundaries.append(ChapterBoundary(
                title, (start, end), BoundaryStatus.CONFIRMED,
                0.95 if explicit else 0.80, tuple(evidence),
            ))
        else:
            boundaries.append(ChapterBoundary(
                title, (start, end), BoundaryStatus.UNKNOWN,
                0.45, ('short_isolated_line', shape),
            ))
    return boundaries
