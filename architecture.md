# Architecture

Status: **APPROVED — building against this.** Decisions and their reasons live in `context.md` section 5.
Plain-language description of how the Fact Knowledge Layer is meant to work.

---

## 1. The idea in one paragraph

A PDF is turned into small pieces of text that each remember where they came from and
what section they sat under. Each piece is scanned cheaply for anything that looks like a
fact. Only the promising pieces are sent to a language model, which rewrites them as
structured **claims** — subject, metric, value, unit, time period, and any qualifiers.
Every claim must quote the source text word-for-word, and we check that the quote really
exists in the PDF before we keep it. Claims are then normalised (units converted, periods
parsed, aliases merged) so that two claims about the same thing become directly
comparable. Finally, claims about the same thing are compared by a set of explicit rules,
and the result is one of: **agrees**, **disagrees**, **only looks like it disagrees**, or
**not enough information**. The language model writes the explanation, but the rules make
the decision, so the reasoning can be audited and reproduced.

---

## 2. Why this shape

The assignment says a graph or a visualization alone is not the answer, and that the
interesting part is *how facts are discovered, grounded, compared and explained*. So the
design puts almost all of its weight on four things:

1. **Grounding** — a claim is thrown away if its quote is not literally in the PDF.
2. **Context capture** — most "contradictions" in real filings are resolved by a detail
   sitting in a table caption or a section heading, not in the sentence itself. We carry
   that context down onto every claim.
3. **Explicit comparison rules** — the verdict comes from comparing named dimensions, not
   from asking a model "do these agree?". The model explains; it does not adjudicate alone.
4. **Honesty** — everything the system rejects or is unsure about is stored and shown,
   rather than silently dropped.

---

## 3. The pipeline

```
PDF
 |
 |-- 1. Parse        layout-aware text + tables + word positions
 |-- 2. Segment      blocks that carry their inherited context
 |-- 3. Screen       cheap rules find fact-bearing blocks   (no LLM)
 |-- 4. Extract      LLM turns blocks into structured claims (+ quote check)
 |-- 5. Normalise    units, periods, entities, metric names
 |-- 6. Link         find claims that are about the same thing
 |-- 7. Reconcile    rules decide the verdict, LLM writes the reason
                     |
                     +--> SQLite --> API --> UI
```

### Step 1 — Parse
- Read the PDF with a layout-aware extractor. Keep, for every word, its page and its
  position on the page.
- **Detect multi-column pages** by looking for a vertical band of whitespace running down
  the page, and read each column separately. Without this, two-column reports (the RBI
  annual report) produce welded, nonsense sentences.
- Extract tables separately from prose, because a table cell's meaning comes from its row
  and column headers, not from the words next to it.
- Strip repeated headers and footers by finding lines that appear on most pages.
- Hash the file so re-uploading the same PDF is a no-op.

### Step 2 — Segment, and carry context down
Each block of text is stored with the context it inherits:
- the trail of section headings above it,
- the table title and column/row headers, if it is a table cell,
- any unit declared for the whole table ("in Rs. million, unless otherwise stated"),
- the statement basis if stated (standalone vs consolidated),
- document-level facts: publisher, document type, publication date, reporting period.

This is the single most important step for the reconciliation to work.

### Step 3 — Screen (cheap, no model calls)
A deterministic pass scores each block for whether it can contain a fact: does it have
numbers, currency symbols, percentages, dates, period labels, units, or entity-state verbs
("appointed", "resigned", "ceased")? Low-scoring blocks are skipped.

This is what makes large PDFs practical — a 100-page report typically has far fewer
fact-dense blocks than total blocks, so model cost tracks the interesting content, not the
page count.

### Step 4 — Extract claims
Fact-bearing blocks are sent to the language model in batches, with their inherited
context attached, and it returns structured claims. The proposed shape of a claim:

```jsonc
{
  "subject":   "Delhivery Limited",        // who/what the fact is about
  "metric":    "revenue from operations",  // what is being measured or stated
  "value":     { "raw": "81,415.38", "number": 81415.38,
                 "unit": "INR", "scale": "million",
                 "normalized": 81415380000 },     // canonical base unit
  "period":    { "label": "FY24", "type": "fiscal_year",
                 "start": "2023-04-01", "end": "2024-03-31" },
  "qualifiers":{ "basis": "consolidated",   // open bag - new keys allowed
                 "segment": null,
                 "vintage": "audited" },
  "kind":      "numeric",                  // or "semantic" / "entity_state"
  "evidence":  { "doc_id": "...", "page": 22,
                 "quote": "Revenue from Operations ... 81,415.38",
                 "bbox": [0, 0, 0, 0] },
  "confidence": 0.87,
  "notes":     "unit taken from table caption"
}
```

**Grounding check:** the returned `quote` is matched against the actual page text. If it
is not there (allowing for whitespace differences), the claim is rejected and logged as a
hallucination. This is a hard gate, and the reject log becomes part of the Case 4 story.

### Step 5 — Normalise
- **Units:** crore, million, billion, lakh, percent, tonnes, million units. Everything is
  converted to one base unit so numbers can be compared directly.
- **Periods:** `FY24`, `FY 2023-24`, `year ended March 31, 2024`, `Q4 FY24`, `9M FY22`,
  `April-November 2024`, `CY2024` all parse to a start date, an end date and a type.
  Indian fiscal years (April-March) are handled explicitly.
- **Negatives:** `(452)` and `Rs. (452) Cr` are negative.
- **Entities:** "Delhivery Limited", "the Company", "our Company", "Delhivery" resolve to
  one entity. Resolution is by string similarity plus the document's own declared aliases,
  not a hard-coded list.
- **Metric names:** an internal registry maps different wordings to one canonical metric.

### Step 5b — The registry (how the schema grows on its own)
Rather than a fixed list of metrics, the system keeps a **metric registry** that starts
empty. When a new metric label appears, it is compared (by embedding similarity and string
similarity) against everything already registered. Close enough, and it is recorded as an
alias of an existing metric. Not close, and it is registered as a **new** metric type. The
registry is visible in the UI, so you can watch the schema grow as documents are added.
This covers the "schema that evolves dynamically" brownie point and is also what makes the
system work on unseen document types.

### Step 6 — Link
Comparing every claim to every other claim does not scale. Instead:
- **Block** candidates by (entity, canonical metric). Only claims in the same block can be
  compared.
- Within a block, rank by embedding similarity of the metric phrase and its context.
- Emit candidate pairs.

Adding a new document only compares that document's new claims against the existing index.
Nothing is rebuilt. This covers the "incremental" brownie point.

### Step 7 — Reconcile
For each candidate pair, first compute a **dimension diff**: which of `period`, `unit`,
`basis`, `segment`, `vintage`, `subject`, `source organisation` differ? Then apply rules:

| All key dimensions match? | Values close? | Verdict |
|---|---|---|
| Yes | Yes (within tolerance for rounding) | **CORROBORATES** |
| Yes | No | **CONTRADICTS** |
| No, and the differing dimension plausibly explains the gap | either | **RECONCILED_BY_CONTEXT** (names the axis: time / scope / units / basis / vintage) |
| Cannot tell | — | **UNRESOLVED** |

The rules produce the verdict *and* a machine-readable trace of why. The language model is
then asked to write a short plain-English explanation, constrained to the two evidence
quotes and the computed diff. It is also used as a tie-breaker on `UNRESOLVED` pairs, with
its answer recorded separately as "model judgement" so it is never confused with a rule
result.

Tolerance for "close" is relative, and widened when one side is visibly rounded
(Rs. 8,142 Cr vs Rs. 8,141.54 Cr is a rounding match, not a contradiction).

---

## 4. Storage

**SQLite**, one file, no server to install. Tables:

- `documents` — file hash, name, publisher, type, dates, page count
- `pages` — page text, per-page word positions
- `blocks` — text block, its inherited context, position
- `claims` — the structured facts above
- `evidence` — quote, page, character span, bounding box (one per claim, at least)
- `entities`, `metrics`, `metric_aliases` — the registries
- `embeddings` — vectors for linking
- `relations` — pair, verdict, dimension diff, explanation, model-vs-rule provenance
- `issues` — rejected extractions, failed quote checks, parse warnings (this is what the
  Case 4 "failures" view reads from)

Why SQLite and not a graph database: the assignment explicitly says a graph database is not
the interesting part, and relations here are pairwise with rich attributes, which is a
table. It also means the grader runs one command with no infrastructure.

---

## 5. API (proposed)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/documents` | Upload a PDF, returns a job id |
| GET | `/api/jobs/{id}` | Progress of processing (streamed) |
| GET | `/api/documents` | List documents |
| GET | `/api/facts` | Filter facts by entity, metric, period, document |
| GET | `/api/facts/{id}` | One fact with its evidence |
| GET | `/api/facts/{id}/evidence.png` | Cropped image of the source page, highlighted |
| GET | `/api/relations` | Filter by verdict (agrees / disagrees / reconciled / unresolved) |
| GET | `/api/relations/{id}` | Full reasoning trace for one relation |
| GET | `/api/search` | Search facts by text |
| GET | `/api/schema` | The metric registry as it currently stands |
| GET | `/api/issues` | Everything the system rejected or flagged |

---

## 6. UI (proposed)

One page, served by the same server, no build step. Sections:
- **Upload** — drop a PDF, watch progress.
- **Facts** — filterable table; clicking a fact shows the exact quote and the page image.
- **Relations** — grouped by verdict. Each card shows both facts side by side, both
  quotes, the dimension diff, and the explanation.
- **Schema** — the metric registry, growing as documents are added.
- **Issues** — the honest list of what failed.

---

## 7. Things that will be hard, and the plan for each

| Problem | Plan |
|---|---|
| Two-column pages weld together | Gutter detection; per-column reading order |
| A table's units are in its caption | Context inheritance (step 2) |
| `(452)` means minus 452 | Explicit negative handling in normalisation |
| Footnote markers change a number's meaning | Capture footnotes into the claim's notes; lower confidence |
| Same metric, different words | Metric registry with alias clustering |
| Fiscal vs calendar year | Explicit period parser with fiscal-year awareness |
| Model invents a quote | Hard quote-verification gate; rejects are logged |
| 500+ pages is slow and expensive | Cheap screening pass; batching; caching by content hash |
| Grader has no API key | Ship a pre-computed results database and a no-key fallback path |

---

## 8. Chosen stack

| Layer | Choice |
|---|---|
| Language | Python 3.13 |
| Web server | FastAPI + uvicorn, serving the API and the UI from one process |
| UI | One static HTML page with plain JavaScript. No build step. |
| Storage | SQLite, one file |
| PDF text and layout | PyMuPDF |
| PDF tables | pdfplumber |
| Language model | Gemini `gemini-flash-lite-latest` by default, behind an adapter that also speaks OpenAI, Anthropic and Ollama |
| Embeddings | Ollama `nomic-embed-text`, falling back to character n-gram similarity |
| Tests | pytest, focused on the normalisers and the reconcile rules |

Remaining open items are tracked in `context.md` section 6.
