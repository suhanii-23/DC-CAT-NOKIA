# DC CAT — Document Quality Check prototype

A Nokia internship prototype for automated document quality checks
(broken links, keyword search, spell/terminology check) over PDF and
DOCX documents. Three teams build one feature each, in parallel, against
a shared contract.

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
- **Load models lazily**, once per instance, via the `self._model`
  pattern already used as a stub in `keyword_search` and `spell_check`
  — never inside `process()`.
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
features/broken_links/         worked example — fully implemented
features/keyword_search/       lexical search implemented; TODO: BGE + FAISS
features/spell_check/          allow-list + difflib implemented; TODO: T5
app/cli.py                     python -m app.cli <file|folder> --query X --excel out.xlsx
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

`pytest tests/ -q` must stay green after every change. A failing test
means the code is wrong — don't edit the test to make it pass.

## Feature notes

- **broken_links** (worked example): flags internal links whose target
  page is out of range, and links to named destinations that don't
  exist. Classifies the reference type (Section/Figure/Table/Appendix/
  Chapter) by regex, and suggests a fix only from real headings — exact
  number match is 0.95 confidence, an adjacent sibling number is 0.72,
  otherwise no suggestion is returned.
- **keyword_search**: lexical occurrence count + page numbers + snippet
  today. `_ensure_model` in `service.py` is where BGE embeddings + FAISS
  would plug in for semantic search — not wired into `process()` yet.
- **spell_check**: a terminology allow-list (never flags `gNodeB`,
  `MOCN`, `RSRP`, `X2`, `ERR#01`, `airscale_rnc`) plus a `difflib`
  comparison against a small set of commonly confused real-word pairs
  (e.g. "form" vs "from"). `_ensure_model` is where a local T5
  grammar-correction pass would plug in — not wired into `process()` yet.

## New dependencies

Ask before adding one, and say why an existing dependency in
`requirements.txt` won't do.
