"""Regression for morphology-backed person admission in Spectrum."""
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(REPO_ROOT))

from app import TensionMapRequest, entropy_map  # noqa: E402


def test_function_words_are_not_persons_but_animate_noun_is() -> None:
    text = (
        "«И вот наступило утро. Она молчала. Все-таки Лис пришёл к "
        "Маленькому Принцу. Лис сказал: — Вот мой секрет.»"
    )
    result = asyncio.run(entropy_map(TensionMapRequest(text=text)))
    person_mentions = [
        token for token in result["data"]
        if token.get("is_entity")
        and token.get("entity_type") == "person"
        and token.get("confidence", 0) >= 0.6
    ]

    assert not any(
        token["word"].lower() in {"и", "она", "все-таки"}
        for token in person_mentions
    )
    assert any(token["word"] == "Лис" for token in person_mentions)
