# DC CAT — Document Quality Check prototype

A Nokia internship prototype for automated document quality checks
(broken links, keyword search, spell/terminology check) over PDF and
DOCX documents. Three teams build one feature each, in parallel, against
a shared contract.

## Status

- `broken_links` — **done**, the worked example. Fully implemented and tested.
- `keyword_search` — **not started**. `features/keyword_search/service.py`
  is an empty file, waiting on its owner.
- `spell_check` — **not started**. `features/spell_check/service.py` is
  an empty file, waiting on its owner.

This is expected, not broken: `app/cli.py` and `tests/test_contract.py`
both load each feature's class dynamically and skip it if it isn't
written yet, so `broken_links` keeps running and testing on its own.
Right now `pytest tests/ -q` reports **7 passed, 4 skipped** — the 4
skips are the two missing features' tests, not failures. Once someone
adds a class to one of the empty files, the CLI and test suite pick it
up automatically; no other file needs to change.

## The contract comes first

`common/contracts.py` is the frozen inter-team agreement. Every feature
depends on it; it depends on nothing else in this repo. **Do not modify
it** — if a feature genuinely needs a contract change, that's a
cross-team conversation, not a local edit. Feature-specific data belongs
in `Finding.details` (a free-form dict), not in new contract fields.

Every feature implements the `FeatureModule` protocol:

```python
class MyFeatureService:
    name = "my_feature"
    def is_available(self) -> bool: ...
    def supports(self, document: Document) -> bool: ...
    def process(self, document: Document, options: dict | None) -> FeatureResult: ...
    def report_columns(self) -> list[str]: ...
```

Rules that keep three parallel teams from breaking each other:

- **`process()` must never raise.** Catch everything internally and
  return `FeatureResult(status="failed", error=...)`.
- **Stay in your feature folder.** Don't edit another team's
  `features/<other>/`, or `common/parser.py` / `common/excel.py`
  (beyond adding your own entry where the code says so).
- **Load models lazily**, once per instance, via a `self._model = None`
  in `__init__` plus an `_ensure_model()` method — never inside
  `process()`. See `features/broken_links/service.py` for the general
  shape of a feature (it doesn't need a model, but the method layout is
  the same).
- **Never invent evidence.** `broken_links` only ever suggests headings
  that exist in `document.headings`; if the evidence is weak, it
  returns no suggestion instead of guessing.
- **Fully local.** No cloud APIs, no external LLM calls, no telemetry,
  no AI vendor SDK dependencies.
- **Don't log document text** (avoids leaking document contents into
  logs/CI output).

## Repo layout

```
common/contracts.py           Document, Page, Paragraph, Heading, LinkAnnotation,
                               Finding, FeatureResult, FeatureModule (Protocol)
common/parser.py               PDF (PyMuPDF) / DOCX (python-docx) -> Document
common/excel.py                Summary sheet + one sheet per feature
features/broken_links/         worked example — done, fully implemented
features/keyword_search/       empty — not started, owner TBD
features/spell_check/          empty — not started, owner TBD
app/cli.py                     python -m app.cli <file|folder> --query X --excel out.xlsx
                                (loads feature classes dynamically; skips ones not yet written)
fixtures/make_fixture.py       generates fixtures/sample.pdf for local testing
tests/test_contract.py         parametrised over all three features
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Workflow

```bash
python fixtures/make_fixture.py
pytest tests/ -q
python -m app.cli fixtures/sample.pdf --query authentication --excel report.xlsx
```

`pytest tests/ -q` must stay green after every change (skips for
not-yet-implemented features are fine; failures are not). A failing test
means the code is wrong — don't edit the test to make it pass.

## Feature notes

- **broken_links** (done, the worked example): flags internal links
  whose target page is out of range, and links to named destinations
  that don't exist. Classifies the reference type (Section/Figure/
  Table/Appendix/Chapter) by regex, and suggests a fix only from real
  headings — exact number match is 0.95 confidence, an adjacent sibling
  number is 0.72, otherwise no suggestion is returned.
- **keyword_search** (not started): planned as lexical occurrence count
  + page numbers + snippet, with a documented spot for BGE embeddings +
  FAISS (semantic search) to plug in later via a lazy `_ensure_model`.
  Whoever picks this up: `features/broken_links/service.py` is the
  reference shape to follow (constructor, `is_available`/`supports`/
  `process`/`report_columns`, `process()` wrapped in try/except).
- **spell_check** (not started): planned as a terminology allow-list
  (never flag `gNodeB`, `MOCN`, `RSRP`, `X2`, `ERR#01`, `airscale_rnc`)
  plus a `difflib` comparison against commonly confused real-word pairs
  (e.g. "form" vs "from"), with a documented spot for a local T5
  grammar-correction pass to plug in later. Watch out: a naive
  `difflib.get_close_matches` over every word will flag short common
  words (e.g. "the" fuzzy-matches "then", "for" fuzzy-matches "form") —
  guard with a common-words stoplist and a minimum word length before
  falling back to fuzzy matching.

## New dependencies

Ask before adding one, and say why an existing dependency in
`requirements.txt` won't do.
