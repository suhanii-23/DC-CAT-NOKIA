# DC CAT — repo summary for Claude

Nokia internship prototype: automated document quality checks (broken
links, keyword search, spell/terminology check) over PDF and DOCX. Three
people build one feature each, in parallel, against a shared contract.

## Current state

- `common/contracts.py`, `common/parser.py`, `common/excel.py`, `app/cli.py`,
  `fixtures/make_fixture.py`, `tests/test_contract.py` — done and working.
- `features/broken_links/service.py` — **fully implemented**, the worked
  example. All its tests pass.
- `features/keyword_search/service.py` — **empty**. Owned by a teammate,
  not yet started.
- `features/spell_check/service.py` — **empty**. Owned by a teammate, not
  yet started.

This is intentional, not broken. `app/cli.py` and `tests/test_contract.py`
both dynamically import each feature's class and skip it gracefully if the
class doesn't exist yet (see `_load_feature` in `app/cli.py` / `_load` in
`tests/test_contract.py`). So right now:
- `pytest tests/ -q` → 7 passed, 4 skipped (the skips are the two missing
  features' tests — expected, not a regression).
- `python -m app.cli fixtures/sample.pdf --query authentication --excel report.xlsx`
  runs fine and only reports `broken_links`, printing a `(note: ... not
  implemented yet, skipping)` line for the other two.

When someone fills in `KeywordSearchService` or `SpellCheckService`, both
the CLI and the test suite pick it up automatically — no other file needs
to change.

## The contract is frozen

`common/contracts.py` defines `Document`, `Page`, `Paragraph`, `Heading`,
`LinkAnnotation`, `Finding`, `FeatureResult`, and the `FeatureModule`
protocol every feature implements. **Don't modify it.** If a change seems
necessary, that's a cross-team conversation — stop and explain instead of
editing. Feature-specific data goes in `Finding.details` (a free-form
dict), never in new contract fields.

## Rules that apply to any code touching this repo

- `process()` must **never raise** — catch everything internally, return
  `FeatureResult(status="failed", error=str(exc))`.
- Stay inside your own `features/<name>/`. Don't edit another team's
  feature folder, `common/parser.py`, or `common/excel.py`.
- Load any model lazily, once, via `self._model = None` in `__init__`
  plus an `_ensure_model()` method — never inside `process()`.
- `broken_links`'s suggestions only ever reference headings that exist in
  `document.headings` — never invent a heading, page, figure, or table
  number. Weak evidence → no suggestion, not a guess.
- Fully local: no cloud APIs, no external LLM calls, no telemetry, no AI
  vendor SDK dependency.
- Don't log document text.
- New dependency → ask first, and say why an existing one in
  `requirements.txt` won't do.

## Workflow

```bash
source .venv/bin/activate          # venv already created; deps installed
python fixtures/make_fixture.py    # regenerates fixtures/sample.pdf (gitignored)
pytest tests/ -q                   # must stay green (skips for unimplemented features are fine)
python -m app.cli fixtures/sample.pdf --query authentication --excel report.xlsx
```

A failing test means the code is wrong — don't edit the test to make it
pass.

## Commits

Plain conventional commits only. No `Co-Authored-By` trailers, no
"Generated with Claude Code" lines, no AI attribution — there used to be
a `.claude/settings.json` enforcing this but it was deleted; keep doing
it manually regardless. Don't commit PDFs other than `fixtures/sample.pdf`
(and that one is gitignored — it's generated, not committed).

## Known gotchas already hit and fixed once

- PyMuPDF: `import fitz` is deprecated, use `import pymupdf as fitz`.
- PyMuPDF: calling `doc.set_toc()` invalidates previously-fetched `Page`
  objects — re-fetch pages (`doc[i]`) *after* `set_toc()`, before
  inserting links (see `fixtures/make_fixture.py`).
- PyMuPDF: a `LINK_NAMED` link's destination name comes back from
  `page.get_links()` under the key `nameddest`, not `name` (even though
  `insert_link()` takes `name` as input).
- openpyxl can't write a Python `list`/`dict` directly into a cell —
  `common/excel.py._to_cell_value` stringifies them first.
- A `difflib.get_close_matches` fuzzy check over all words is too loose:
  short common words like "the"/"for" fuzzy-match confusable-pair keys
  like "then"/"form". `spell_check`'s original implementation (now
  deleted, but worth remembering if reimplementing) guarded this with a
  common-words stoplist and a minimum word length before falling back to
  fuzzy matching.
