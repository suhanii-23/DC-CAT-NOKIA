# DC CAT — Document Quality Check prototype

A Nokia internship prototype for automated document quality checks
(broken links, keyword search, spell/terminology check) over PDF and
DOCX documents. Three teams build one feature each, in parallel, against
a shared contract.

## Status

- `broken_links` — **done**, the worked example. Fully implemented and tested.
- `keyword_search` — **done**. Lexical occurrence counting plus BGE +
  FAISS semantic search. The semantic half needs model weights that are
  **not in the repo** — see [Semantic search setup](#semantic-search-setup-bge-weights).
- `spell_check` — **not started**. `features/spell_check/service.py` is
  an empty file, waiting on its owner.

This is expected, not broken: `app/cli.py` and `tests/test_contract.py`
both load each feature's class dynamically and skip it if it isn't
written yet, so the finished features keep running and testing on their
own. Once someone adds a class to the empty file, the CLI and test suite
pick it up automatically; no other file needs to change.

With the BGE weights provisioned, `pytest tests/ -q` reports
**67 passed, 2 skipped** — the 2 skips are `spell_check`'s tests, not
failures.

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
features/keyword_search/       done — lexical + BGE/FAISS semantic search
features/spell_check/          empty — not started, owner TBD
app/cli.py                     python -m app.cli <file|folder> --query X --excel out.xlsx
                                (loads feature classes dynamically; skips ones not yet written)
fixtures/make_fixture.py       generates fixtures/sample.pdf for local testing
models/bge-base-en-v1.5/       BGE weights — gitignored, provisioned per machine
tests/test_contract.py         parametrised over all three features
tests/test_keyword_search.py   lexical pass
tests/test_keyword_search_semantic.py
                               chunking/selection, a fake encoder, and real-model
                                tests that skip when the weights are absent
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# CPU-only torch FIRST. sentence-transformers pulls torch in as a
# dependency, and on Linux/macOS the default wheel drags in ~2.5 GB of
# CUDA that this project never uses.
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
```

Semantic search additionally needs model weights, which are **not** in
the repo — see the next section. Everything else works without them.

## Semantic search setup (BGE weights)

`keyword_search` runs two passes: a lexical one that always works, and a
semantic one (BAAI/bge-base-en-v1.5 + FAISS) that needs ~438 MB of model
weights. `models/` is **gitignored**, so the weights are never committed
and **every machine must provision them once** — including a fresh clone
on the demo machine.

Nothing is ever downloaded at runtime. The service loads the model with
`local_files_only=True` and sets `HF_HUB_OFFLINE`, so if the weights are
missing it does not reach for the network — it degrades quietly to
lexical-only. That quiet degradation is exactly why you want to run the
verification below *before* demoing.

### 1. Download the weights

From the repo root, with the venv active:

```bash
hf download BAAI/bge-base-en-v1.5 --local-dir models/bge-base-en-v1.5
```

`hf` ships with `huggingface_hub`, which `sentence-transformers` already
installs. On older `huggingface_hub` (< 1.0) the command is
`huggingface-cli download` with the same arguments.

This needs network access. If the demo machine is offline, run the
command elsewhere and copy the resulting `bge-base-en-v1.5/` folder to
`models/` — the weights are plain files, there is no install step.

### 2. Check what you got

```
models/bge-base-en-v1.5/
├── 1_Pooling/config.json
├── config.json
├── config_sentence_transformers.json
├── model.safetensors            <- ~438 MB, the actual weights
├── modules.json
├── sentence_bert_config.json
├── special_tokens_map.json
├── tokenizer.json
├── tokenizer_config.json
└── vocab.txt
```

`model.safetensors` being much smaller than ~438 MB means the download
was interrupted — delete the folder and retry rather than debugging a
truncated file.

Two things that look wrong but are not:

- **`modules.json` references a `2_Normalize/` folder that does not
  exist.** That is normal. sentence-transformers' `Normalize` module
  takes no configuration files, so it is constructed from `modules.json`
  alone. Do not go looking for the folder.
- **A `.cache/huggingface/` folder inside the model directory.** That is
  download bookkeeping from `hf download --local-dir`. Harmless.

### 3. Weights somewhere else (optional)

To keep the weights outside the repo — a shared drive, a path reused
across checkouts — point `DCCAT_BGE_MODEL_PATH` at the directory:

```bash
export DCCAT_BGE_MODEL_PATH=/path/to/bge-base-en-v1.5
```

```powershell
$env:DCCAT_BGE_MODEL_PATH = "C:\path\to\bge-base-en-v1.5"   # PowerShell
```

It must point at the folder *containing* `config.json` and
`model.safetensors`, not at a parent. When unset, the default is
`models/bge-base-en-v1.5/` in the repo root.

### 4. Verify before the demo

The model must be **bge-base** (768-dim). bge-small is a common
mix-up and is silently a different model, so the service checks the
embedding width and refuses rather than returning quietly wrong results.

The fastest check is the test suite, because the two real-model tests
skip themselves when the weights are absent:

```bash
pytest tests/ -q
```

- `67 passed, 2 skipped` — weights are live. The 2 skips are
  `spell_check`, which is genuinely unimplemented.
- `65 passed, 4 skipped` — **weights are missing.** Run `pytest tests/ -q -rs`
  and the two extra skips will say so by name.

For a direct check of the model itself (bash — on PowerShell, save the
body to a `.py` file and run that instead, as `python -c` there does not
take a multi-line string):

```bash
python -c "
from features.keyword_search.service import KeywordSearchService
from common.contracts import Document, Page, Paragraph
doc = Document(path='d.docx', format='docx', page_count=1,
               pages=[Page(number=1, text='x')],
               paragraphs=[Paragraph(text='Users must present valid authentication tokens.', page=1, index=0)])
print(KeywordSearchService().process(doc, {'query': 'login'}).meta['semantic'])
"
```

Prints `ok: 1 result(s) from 1 chunk(s)` when working. Anything starting
`unavailable:` states the reason — missing directory, wrong dimensions,
or a dependency that failed to import.

That status lives in `FeatureResult.meta["semantic"]` and is deliberately
non-fatal, so note that **neither the CLI output nor the Excel report
shows it.** In CLI output the visible sign that semantic search ran is
findings phrased `Passage related to '<query>' ... (similarity 0.xxx, no
exact match)`. If you only ever see exact-match findings, semantic search
is off.

## Workflow

```bash
python fixtures/make_fixture.py
pytest tests/ -q
python -m app.cli fixtures/sample.pdf --query authentication --excel report.xlsx
```

`pytest tests/ -q` must stay green after every change (skips for
not-yet-implemented features are fine; failures are not). A failing test
means the code is wrong — don't edit the test to make it pass.

The first run after provisioning the weights prints a one-off
`Loading weights` progress bar and takes a second or two longer; the
model is then held in memory and reused for every document in a folder
walk.

## Feature notes

- **broken_links** (done, the worked example): flags internal links
  whose target page is out of range, and links to named destinations
  that don't exist. Classifies the reference type (Section/Figure/
  Table/Appendix/Chapter) by regex, and suggests a fix only from real
  headings — exact number match is 0.95 confidence, an adjacent sibling
  number is 0.72, otherwise no suggestion is returned.
- **keyword_search** (done): two passes over the document, counting by
  paragraph where the document has paragraphs and by page otherwise
  (never both — the parser derives paragraphs *from* page text, so
  counting both double-counts every match).
  1. **Lexical**, always runs, needs nothing. Case-insensitive
     whole-token matching, tolerant of line wrapping, with a snippet per
     hit. Authoritative — never suppressed or replaced by semantic
     results.
  2. **Semantic**, runs when the BGE weights are present. Returns up to
     5 extra passages related to the query without containing it
     verbatim (e.g. "login" surfacing a paragraph about authentication).
     Chunks that already contain an exact match are dropped, since the
     lexical pass has them covered.

  Semantic snippets are verbatim document text — never paraphrased or
  generated. Similarity scores are recorded on every semantic finding
  but **nothing is filtered by score**: an honest threshold needs
  calibrating against real documents, and a borrowed constant would be
  meaningless against BGE's narrow score band.

  `is_available()` always returns `True` on purpose. Returning `False`
  when the weights are missing would make the CLI skip the whole feature
  and take working lexical search down with it.
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
