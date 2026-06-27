# Morphological Transformations Demo

Interactive visualization of Russian word inflections, feminitive generation, and morphotactic transition rules.

This application is built with **FastAPI** on the backend (integrating directly with the `logos` SQLite paradigm database) and a high-end, responsive **Vanilla CSS & JS** dark-mode interface with glassmorphic panels and spring-based animations.

## Key Features

1. **Feminitive Generator**:
   - Generates feminine professional/role nouns from masculine terms based on suffix rules (`ец -> ейка/анка/ка`, `тель -> тельница`, `ик -> ица`, etc.).
   - **Stylistic Registers**: Filters colloquial forms (e.g., `блогерка` is blocked under `official` style; only whitelisted terms like `космонавтка` or `учительница` are permitted).
   - **Homonym Collision Protection**: Automatically queries `ru_paradigms.sqlite3` to block feminitive candidates that collide with existing inanimate objects (e.g., blocking `пилотка` since it's a cap, or `электричка` as a train).

2. **Targeted Inflector**:
   - Decline and conjugate nouns, adjectives, and verbs based on the target grammatical description (e.g., `plur,gent`, `sing,datv`).
   - Uses the SQLite-backed paradigm database.

3. **Morphotactic Transition Rules**:
   - Highlighting the exact transition from masculine stems to feminine suffixes using dynamic LCP (Longest Common Prefix) splits.

## Installation & Running

Ensure you have FastAPI and Uvicorn installed:

```bash
pip install fastapi uvicorn pydantic
```

Run the local server:

```bash
python3 app.py
```

Open your browser and navigate to:
```
http://127.0.0.1:8000
```
