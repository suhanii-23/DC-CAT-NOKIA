# DC CAT — Document Quality Check prototype

A Nokia internship prototype for automated document quality checks
(broken links, keyword search, spell/terminology check) over PDF and
DOCX documents. Four people build one feature each, in parallel,
against a shared contract.

## Status

Everything below is implemented and tested.

| Feature | Status |
|---|---|
| `broken_links` | **Done.** Flags internal cross-references that no longer resolve, classifies the reference type, and suggests a fix only from headings or captions that exist in the document. Deterministic, no AI, runs fully offline. |
| `keyword_search` | **Done.** Lexical occurrence counting plus BGE + FAISS semantic search over one document. Degrades to lexical-only when the model weights are absent — see [Semantic search setup](#semantic-search-setup-bge-weights). |
| `spell_check` | **Done.** Nokia terminology allow-list (built-in or loaded from Excel), local T5 contextual correction with a deterministic confusion-map fallback, difflib word-level diff, and an edit-distance filter that separates real typos from T5 rewordings — see [Spell check setup](#spell-check-setup-t5-weights). |
| `multi_doc_keyword_search` | **Done.** One exact keyword across many documents at once, purely lexical. A *corpus* feature: it runs once over the whole document set rather than once per document, through its own LangGraph graph (`corpus_graph`) — see [Multi-document keyword search](#multi-document-keyword-search). |

`app/cli.py`, `app/agent/graph.py` and `app/mcp_server.py` are the
integration points; each feature's own logic lives entirely in its
`features/<name>/` folder and all three only delegate to it.

There's also a browser GUI: a React/Vite frontend (`frontend/`) talking
to a FastAPI backend (`api/main.py`) that wraps the same feature
services — see [Running the web GUI](#running-the-web-gui).

`pytest tests/ -q` reports **308 passed** with the BGE/T5 weights
provisioned on top of `requirements.txt`, or **306 passed, 2 skipped**
right after `pip install -r requirements.txt` on a fresh clone before
downloading any weights — the ML-backed tests are written to skip
themselves rather than fail when weights aren't present. 0 failed
either way — see [Testing](#testing).

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

Rules that keep parallel teams from breaking each other:

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
  or captions that exist in the document; if the evidence is weak, it
  returns no suggestion instead of guessing.
- **Fully local.** No cloud APIs, no telemetry, no AI vendor SDK
  dependencies. (`spell_check`'s T5 weights are fetched from Hugging
  Face on first use and cached — see the note in
  [Spell check setup](#spell-check-setup-t5-weights) — everything else
  never reaches the network.)
- **Don't log document text** (avoids leaking document contents into
  logs/CI output).

## Repo layout

```
common/contracts.py            Document, Page, Paragraph, Heading, LinkAnnotation,
                                Finding, FeatureResult, FeatureModule (Protocol)
common/parser.py                PDF (PyMuPDF) / DOCX (python-docx) -> Document
common/excel.py                 Summary sheet + one sheet per feature
features/broken_links/          done — cross-reference checking, no model
features/keyword_search/        done — lexical + BGE/FAISS semantic search
features/spell_check/           done — terminology allow-list + T5 correction
  ├── service.py                 FeatureModule entry point (process())
  ├── model.py                   T5CorrectionModel, lazy-loaded, HF fallback
  ├── preprocessing.py           sentence splitting + protected-term filtering
  ├── utils.py                   difflib diff + Levenshtein edit-distance filter
  ├── tools/terminology.py       Nokia terminology allow-list (Excel or built-in)
  └── agent/                     not wired in yet — see Open items in CLAUDE.md
features/multi_doc_keyword_search/
                                done — one exact keyword across many documents,
                                 lexical only; matcher.py (the only matching
                                 logic) / discovery.py / service.py / cli.py
app/agent/state.py              AgentState (one document) + CorpusState (many)
app/agent/graph.py              agent_graph (per document) + corpus_graph (per run)
app/mcp_server.py               the features exposed as MCP tools
app/cli.py                      python -m app.cli <file|folder> --query X --excel out.xlsx
                                 (loads feature classes dynamically; skips ones not yet written)
api/main.py                     FastAPI backend for the web GUI — wraps the same
                                 feature services and LangGraph graphs as the CLI
frontend/                       React + Vite GUI (upload a document, pick features,
                                 view findings) — talks to api/main.py over HTTP
fixtures/make_fixture.py        generates fixtures/sample.pdf for local testing
fixtures/make_demo.py           generates fixtures/demo_manual.pdf
fixtures/nokia105.pdf           real Nokia guide used for broken_links regression
models/bge-base-en-v1.5/        BGE weights — gitignored, provisioned per machine
tests/                          11 files, 308 tests — test_contract.py is
                                 parametrised over all four features
```

## Installing

### 1. Backend (Python)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# CPU-only torch FIRST. sentence-transformers and transformers pull torch
# in as a dependency, and on Linux/macOS the default wheel drags in
# ~2.5 GB of CUDA that this project never uses.
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
```

`requirements.txt` covers the CLI, the MCP server, and the FastAPI
backend (`fastapi`, `uvicorn`, `python-multipart`) in one install —
there's no separate backend-only requirements file.

Two optional, larger pieces degrade quietly rather than block install:

- **Semantic search** (`keyword_search`) needs ~438 MB of BGE model
  weights that are **not** in the repo — see
  [Semantic search setup](#semantic-search-setup-bge-weights).
  Without them, lexical search still works.
- **T5 spell correction** (`spell_check`) fetches its weights from
  Hugging Face the first time it runs and caches them — see
  [Spell check setup](#spell-check-setup-t5-weights). Without network
  access, it falls back to a small built-in confusion-map.

### 2. Frontend (only if you want the web GUI)

```bash
cd frontend
npm install
```

Create `frontend/.env.local` (gitignored, so each machine needs its
own) pointing at wherever the backend runs:

```
VITE_API_BASE_URL=http://localhost:8000
```

## Executing the code

There are three ways to run the tool. All three call the same feature
services underneath.

### Command line

```bash
python -m app.cli fixtures/demo_manual.pdf --query login --excel report.xlsx
python -m app.cli fixtures/demo_manual.pdf --features broken_links
python -m app.cli fixtures/demo_manual.pdf --features spell_check,broken_links
python -m app.cli fixtures/demo_manual.pdf --ask "are any cross-references broken?"
python -m app.cli docs/ --features multi_doc_keyword_search --query authentication
```

`--features` takes a comma-separated list (default `all`); `--ask`
takes a plain-English request and routes it to features for you
(prints which features it picked and why); `--query` is the keyword for
`keyword_search` / `multi_doc_keyword_search`; `--excel PATH` writes a
report alongside the terminal output.

### MCP server

```bash
python -m app.mcp_server
```

Exposes each feature as an MCP tool (`check_broken_links`,
`search_keyword`, `check_spelling`, `search_documents_for_keyword`) for
an MCP-aware client to call directly.

### Running the web GUI

Two processes, in two terminals, both from the repo root:

```bash
# terminal 1 — backend
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`). Upload a
PDF/DOCX, pick features, optionally give a keyword, and view findings in
the browser. `api/main.py` exposes `GET /health`, `POST /analyze` (one
document) and `POST /analyze-multiple` (many documents, needed for
`multi_doc_keyword_search`); CORS is pre-configured for
`localhost:5173`/`5174`.

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

The fastest check is the test suite, since the real-model tests skip
themselves when the weights are absent:

```bash
pytest tests/ -q -rs
```

Run `-rs` to see skip reasons by name if the count looks off.

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

## Spell check setup (T5 weights)

`spell_check` uses a T5 grammar-correction model
(`vennify/t5-base-grammar-correction` by default) via
`transformers.T5ForConditionalGeneration.from_pretrained`. Unlike the BGE
setup above, this is **not** offline-only: the first call downloads and
caches the weights through the normal Hugging Face cache
(`~/.cache/huggingface/`), so the very first run needs network access.
Every run after that uses the cache and needs nothing.

If the download fails or `transformers`/`torch` aren't installed, the
service catches the exception and falls back to a small, curated
confusion-map (`form`/`from`, `thier`/`their`, `recieve`/`receive`, …)
so the feature still returns results — just without contextual
correction.

To point at a different model size once one has been benchmarked, set:

```bash
export NOKIA_SPELLCHECK_T5_MODEL=<model name or local path>
```

To load the Nokia terminology allow-list from an Excel workbook instead
of the small built-in default list, pass `terminology_path` in the
feature options (see `features/spell_check/tools/terminology.py`).

## Testing

```bash
source .venv/bin/activate
pytest tests/ -q
```

- **308 passed** with both the BGE and T5 weights provisioned (the
  state of this repo checkout).
- **306 passed, 2 skipped** right after `pip install -r
  requirements.txt` on a fresh clone, before downloading any weights —
  the 2 skips are the real-BGE-model tests in
  `tests/test_keyword_search_semantic.py`. T5 has no equivalent skip:
  `spell_check` tests pass either way, since `model.py` falls back to
  its confusion-map instead of failing when there's no cached T5 model
  and no network.
- **286 passed, 22 skipped** if `torch`/`transformers`/
  `sentence-transformers`/`faiss-cpu` aren't installed at all (e.g. the
  CPU-only-torch install step was skipped, or a CI box can't take the
  extra weight). Every feature's `is_available()` still returns `True`
  and degrades to its non-ML path — see the "degrade, don't crash" rule
  in `CLAUDE.md`. `features/spell_check/model.py` imports `torch`
  inside a `try/except ImportError` for exactly this case; without that
  guard, the bare top-level import used to take down the whole
  `spell_check` module (and with it, `check_spelling`'s MCP
  registration) on any machine without torch.
- 0 failed in all three cases. Run `pytest tests/ -q -rs` to see skip
  reasons by name if a count looks unexpected.

`pytest tests/ -q` must stay green after every change (skips for
missing optional weights are fine; failures are not). **A failing test
means the code is wrong — don't edit the test to make it pass.**

Regenerate fixtures if you change the scripts that build them (and
commit the regenerated PDF, or the parser tests compare a new script
against an old document):

```bash
python fixtures/make_fixture.py     # -> fixtures/sample.pdf
python fixtures/make_demo.py        # -> fixtures/demo_manual.pdf
```

Test on `fixtures/nokia105.pdf` and the NSP guides, not only the
synthetic fixtures — every significant bug so far has surfaced on a
real document and none on the generated ones.

## Feature notes

- **broken_links** (done): flags internal links whose target page is
  out of range, and links to named destinations that don't exist.
  Classifies the reference type (Section/Figure/Table/Appendix/Chapter)
  by regex, and suggests a fix only from real headings or captions —
  exact number match is 0.95 confidence, an adjacent sibling number is
  0.72, otherwise no suggestion is returned.
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
- **spell_check** (done): sentences are extracted from
  `document.paragraphs`, Nokia terminology and identifier-shaped words
  (ALL-CAPS, digits/underscores, mixed-case like `gNodeB`) are protected
  from the outset, and the remaining text goes through T5 contextual
  correction (falling back to a curated confusion-map — see
  [Spell check setup](#spell-check-setup-t5-weights)). A `difflib`
  word-level diff between the original and corrected sentence produces
  candidate changes, and a Levenshtein edit-distance filter (≤2, or ≤1
  for words of three characters or fewer) rejects T5 rewordings that
  aren't actually spelling fixes — `difflib.ratio()` alone can't tell a
  real typo from a rewording (0.75 vs 0.74 are indistinguishable).
  `features/spell_check/agent/` is a not-yet-wired-in agentic
  verification layer, pending Nokia's approved LLM infrastructure
  decision — see the Open items in `CLAUDE.md`.
- **multi_doc_keyword_search** (done): one exact keyword across many
  documents, one finding per occurrence. The only *corpus* feature —
  see the next section.

## Multi-document keyword search

Give it **one keyword** and a set of documents; get back **every**
occurrence, grouped by document, with page and surrounding text. It never
stops at the first document, the first page, or the first hit.

```text
User
 │  keyword = "authentication"
 ▼
multi_doc_keyword_search
 ├── document1.pdf   page 2, page 8
 ├── document2.pdf   page 4
 └── document3.pdf   no matches
                     ▼
        3 matches across 2 of 3 documents
```

### A corpus feature, not a per-document one

The other three features run once **per document**: `app/cli.py` parses a
file and `agent_graph` fans it out to the selected feature nodes. This one
runs once over the **whole set**, because the answer it gives — totals,
and which documents matched — only exists across documents.

That is a genuine mismatch with `AgentState`, which holds a single
`document`: making this a node in `agent_graph` would run it once per
file, which is exactly the wrong answer. So it gets its own LangGraph
graph in the same module — still LangGraph, still one orchestrator, no
second execution system:

```text
app/agent/state.py    AgentState (one document)  |  CorpusState (paths)
app/agent/graph.py    agent_graph                |  corpus_graph
                        spell_check              |    multi_doc_keyword_search
                        broken_links             |    collect_results
                        keyword_search           |
                        collect_results          |
app/cli.py             invoked once per file      |  invoked once per run
```

Both graphs are optional in the same way: `app/cli.py` imports them in one
`try`, and falls back to calling the services directly
(`_run_features_directly` / `_run_corpus_features_directly`) when
`langgraph` isn't installed, producing identical results either way. The
graph nodes only delegate — `run_multi_doc_keyword_search` calls
`MultiDocKeywordSearchService.search()` and holds no matching logic.

`app/cli.py` keeps the two kinds in separate lists (`_FEATURE_SOURCES` and
`_CORPUS_SOURCES`) because they are invoked differently, but
**`--features all` runs both kinds** — "all" means all. Nothing in the
project requires corpus features to be held back, and a feature you cannot
reach from the documented command is one nobody will use.

The one special case: a keyword-driven corpus feature has nothing to do
without a keyword, so **`--features all` with no `--query` reports it as
`skipped`**, not as a failure, and prints a note to stderr. That keeps
`python -m app.cli fixtures/sample.pdf --excel report.xlsx` working
exactly as documented. Searching for the empty string is never the
intent; at the service and MCP layer an explicitly empty keyword is still
a validation failure.

```bash
python -m app.cli docs/ --query authentication                     # all, incl. corpus
python -m app.cli docs/ --features multi_doc_keyword_search --query authentication
python -m app.cli docs/ --features broken_links,multi_doc_keyword_search --query auth
python -m app.cli docs/ --features multi_doc_keyword_search --query auth --excel out.xlsx
```

```text
=== multi_doc_keyword_search (3 document(s)) ===
[multi_doc_keyword_search] status=ok findings=3
  document1.pdf
    - (p2) ...User authentication is required before accessing the system....
    - (p8) ...the authentication token expires hourly....
  document2.pdf
    - (p4) ...Authentication failures are logged....
```

The corpus feature contributes one `FeatureResult` to the run, so `--excel`
gives it a sheet like any other feature: a row per occurrence with page,
message, keyword, document, occurrence index, paragraph index,
matched text, and context.

### Through the MCP server

`app/mcp_server.py` registers it as `search_documents_for_keyword(paths,
keyword)`, alongside the three existing tools, whose behaviour is
untouched — the tool is a one-line delegation to
`MultiDocKeywordSearchService.search()`. `paths` takes files,
folders (walked recursively), or a mix; the payload is grouped by
document with `documents_searched`, `documents_with_matches` and
`total_matches`, and per-document match lists capped at 100 with
`"truncated": true` while the counts stay honest.

### Standalone

The feature also has its own CLI: **N documents + 1 keyword → 1 XLSX**.
Pass files, folders, or both. A search covering **two or more documents**
writes an `.xlsx` automatically, named from the keyword.

```bash
python -m features.multi_doc_keyword_search.cli document1.pdf document2.pdf document3.pdf \
    --keyword embedded --excel report.xlsx
python -m features.multi_doc_keyword_search.cli fixtures/ --keyword authentication
# -> keyword_matches_authentication.xlsx
```

`--excel PATH` chooses the path and forces a report even for one
document; `--no-excel` suppresses it.

The report is one sheet, **Keyword Search**, one row per occurrence:

| Document | Page | Keyword | Match | Context |
|---|---|---|---|---|
| document1.pdf | 29 | embedded | embedded | …wireless technology and embedded systems, the cost of hardware… |

`Match` is the word as the document writes it (casing kept); `Context` is
the surrounding sentence, or a word-trimmed window when the sentence is
very long. Header row frozen and filterable, `Context` wrapped. No
severity, confidence or other analysis columns: this is a location
report, not a findings report, so it is written by
`features/multi_doc_keyword_search/report.py` rather than the shared
`common/excel.py` (which always adds those columns). `app/cli.py` still
reports the feature through `common/excel.py`, unchanged.

The terminal gets a short summary: matches per document, the total, and
the report path. A PDF whose pages are mostly images with no text layer
is marked as probably scanned, because a `0` there means "could not be
searched", not "not mentioned".

### It is not semantic search

No embeddings, no vector index, no FAISS, no sentence-transformers, no
LLM, no synonyms, no query expansion, no fuzzy matching. Searching
`authentication` searches for `authentication` and nothing else — it will
never return `login`, `authorization` or `credentials` the way the
semantic half of `keyword_search` deliberately does. The keyword the user
typed is the source of truth.

|  | `keyword_search` | `multi_doc_keyword_search` |
|---|---|---|
| Scope | one document per call | many documents per call |
| Matching | lexical **plus** BGE/FAISS semantic | lexical only |
| Granularity | occurrence *counts* per paragraph/page | one finding **per occurrence** |
| Dependencies | model weights for the semantic half | none beyond the shared parser |

### Matching rules

- **Case-insensitive.** `authentication` matches `Authentication`,
  `AUTHENTICATION`, `AuThEnTiCaTiOn`. `details["match_text"]` reports the
  casing actually found.
- **Whole-word.** `authentication` does not match `preauthentication` or
  `authentications`. Lookarounds rather than `\b`, so a keyword whose
  edges aren't word characters (`ERR#01`) still matches.
- **Whitespace-tolerant.** A multi-word keyword still matches across a
  line break.
- **Hyphenation-tolerant.** A word split across two lines (`em-` / `bedded`)
  or carrying soft hyphens (U+00AD — one 570-page textbook has 1,699 at
  line ends) still matches, and `Match` shows it as one word.
- **Counting unit:** paragraphs where the document has them, pages
  otherwise — never both, since the parser derives paragraphs *from* page
  text and counting both would double-count every match.
- **Reading from disk:** `search()` reads a PDF's page text straight from
  PyMuPDF rather than running the full shared parser, whose paragraph,
  link and outline extraction a keyword search never uses. On a 748-page
  scanned book that cut reading from ~126 s to under 2 s. DOCX still goes
  through the shared parser.

### Output and errors

Each occurrence is one `Finding`; the frozen contract is untouched and
everything feature-specific lives in `Finding.details` — `keyword`,
`document`, `page`, `paragraph_index`, `match_text`, `context`,
`occurrence_index`. `context` is verbatim document text, never
paraphrased or generated.

- **Empty or whitespace-only keyword** → `status: "failed"` with a
  validation message. It never falls back to matching everything.
- **No matches anywhere** → `status: "ok"`, `total_matches: 0`. Not an
  error.
- **A document that can't be read** → recorded in `errors` with its
  reason, and every other document is still searched. The try/except is
  per document, so one corrupt PDF in a folder of fifty doesn't cost you
  the other forty-nine.

### Known limitations

Sequential, no concurrency and no cross-call parse cache. PDFs searched
from disk are searched per page, so `paragraph_index` is empty for them
(page numbers are exact). A match straddling a paragraph or page
boundary is not found. A keyword containing spaces is one literal phrase,
not several keywords. Scanned PDFs have no text to search; there is no
OCR. DOCX text inside tables, headers and footers is not searched, because
the shared parser reads body paragraphs only.

## New dependencies

Ask before adding one, and say why an existing dependency in
`requirements.txt` won't do.
