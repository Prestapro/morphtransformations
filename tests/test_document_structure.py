"""Tests for ternary chapter-boundary detection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from document_structure import BoundaryStatus, detect_chapter_boundaries


def test_explicit_numbered_headings_are_confirmed_chapters():
    text = """Глава I
Начало рассказа.

Глава II
Продолжение рассказа."""

    boundaries = detect_chapter_boundaries(text)

    assert [(boundary.title, boundary.status) for boundary in boundaries] == [
        ('Глава I', BoundaryStatus.CONFIRMED),
        ('Глава II', BoundaryStatus.CONFIRMED),
    ]
    assert all('numbered_heading' in boundary.evidence for boundary in boundaries)


def test_repeated_roman_heading_template_confirms_chapters_without_word_glava():
    text = """I
Первый фрагмент достаточно длинный.

II
Второй фрагмент достаточно длинный.

III
Третий фрагмент достаточно длинный."""

    boundaries = detect_chapter_boundaries(text)

    assert [boundary.status for boundary in boundaries] == [
        BoundaryStatus.CONFIRMED,
        BoundaryStatus.CONFIRMED,
        BoundaryStatus.CONFIRMED,
    ]
    assert all('repeated_heading_template' in boundary.evidence for boundary in boundaries)


def test_isolated_short_line_without_repeated_structure_remains_unknown():
    boundaries = detect_chapter_boundaries("""Начало.

Позже

Текст продолжается.""")

    assert len(boundaries) == 1
    assert boundaries[0].title == 'Позже'
    assert boundaries[0].status == BoundaryStatus.UNKNOWN


def test_scene_separator_is_not_promoted_to_chapter():
    boundaries = detect_chapter_boundaries("""(Входит Иван.)

Он смотрит в окно.""")

    assert boundaries == []
