# Context

This file is the running memory of the project. It records what the task is, what
I found in the data, what was decided, and what is still open. Read this first if
you are picking the project up cold.

Status: **PLAN APPROVED — ready to build.**
Last updated: 2026-09-08

---

## 1. What we were asked to build

Source: `superjoin-vit-2026-assignment.pdf` (Superjoin VIT 2026, Engineering Intern).

Build a **Fact Knowledge Layer**. Given PDFs, the system must:

1. Pull out meaningful facts (numbers and semantic/statement facts).
2. Tie every single fact back to the exact place it came from in the source PDF.
3. Work out when two facts **agree**, **disagree**, or **only look like they disagree**
   until you account for context (time period, scope, units).

Plus:
- A simple **API or UI** to upload PDFs and browse results.
- Must work on **unseen PDFs**. No hard-coded facts, filenames, or per-document rules.
- "A graph database or a visualization alone is not the solution." The grading weight is
  on *how facts are found, grounded, compared and explained*.

### The four cases we must demonstrate
| # | Case | Must show evidence + reasoning? |
|---|------|--------------------------------|
| 1 | A fact corroborated across documents, even if worded differently | Yes |
| 2 | A genuine or likely contradiction | Yes |
| 3 | An apparent contradiction explained by context (time / scope / units) | Yes |
| 4 | An extraction or reasoning failure we found, and how we handled it | No, but must be honest |

### Submission requirements
- Git repo, used meaningfully (real commit history, not one big dump).
- `README.md` with these exact sections: Setup and Run Instructions, Video Demo,
  Approach, Limitations and Next Steps, Additional Notes.
- Demo video, **3 minutes or less**, showing a PDF being processed and all four cases.
- No credentials in the repo. If a paid service is needed, ship enough sample output
  that a grader can evaluate without our account.

### Brownie points (optional)
- Large PDFs without slowing down.
- Many PDFs in one knowledge layer.
- A schema that grows as new kinds of facts appear.
- Adding new documents **incrementally**, without rebuilding everything.

---

## 2. What is in the starter data

Two independent datasets, three PDFs each, in `starter-datasets/starter-datasets/`.

### Dataset A — Delhivery (a listed Indian logistics company)
| File | Pages | What it is |
|---|---|---|
| `01-delhivery-prospectus-2022-excerpt.pdf` | 100 | IPO prospectus, 2022. Financials up to FY21 / 9M FY22, plus board & management history. |
| `02-delhivery-annual-report-fy24-excerpt.pdf` | 100 | Annual report FY 2023-24. Audited financials, directors' report, MD&A, ESG. |
| `03-delhivery-q4-fy24-earnings-presentation.pdf` | 27 | Q4 FY24 investor deck. Same numbers, rounded, in different units. |

### Dataset B — India macroeconomy
| File | Pages | What it is |
|---|---|---|
| `01-india-economic-survey-2024-25-excerpt.pdf` | 89 | Government of India. State of the economy, external sector, inflation. |
| `02-rbi-annual-report-2024-25-excerpt.pdf` | 100 | Reserve Bank of India. Assessment, economic review, appendix tables. |
| `03-imf-india-2025-article-iv-excerpt.pdf` | 95 | IMF staff report on India, 2025. Same economy, different publisher and vintage. |

**Total: ~511 pages.** All six are born-digital (real text, no OCR needed). Verified.

---

## 3. What I verified by hand in the PDFs

These are the facts that make the four required cases achievable. They were found by
inspection to prove the approach is sound — **the system will not hard-code any of them.**

### Case 1 candidate — corroboration across different wording and units
- Earnings deck, p6: `₹8,142 Cr` — "FY24 revenue from services".
- Annual report, p22: `₹81,415.38 million` — "Revenue from Operations", FY24.
- These are the same fact. 81,415.38 million = 8,141.54 crore. The deck rounded up.
  Different unit (Cr vs million), different label, different document type.

### Case 2 candidate — genuine contradiction
- Likely from Dataset B: FY25 real GDP growth is stated by the Economic Survey, the RBI
  and the IMF at slightly different values, because each used a different **data vintage**
  (advance estimate vs provisional estimate vs IMF projection). Same entity, same period,
  different number. To be confirmed by the pipeline, not asserted here.
- Also available in Dataset A: a director listed as active in the 2022 prospectus who is
  recorded as resigned in the FY24 annual report (p24 lists cessations with dates).

### Case 3 candidate — apparent contradiction explained by context
Three clean variants exist in the Delhivery annual report alone:
- **Scope (basis):** p22 shows Revenue from Operations FY24 as `74,540.82` *and* `81,415.38`.
  Not a contradiction — the first is **standalone**, the second is **consolidated**.
- **Scope (metric boundary):** p36, "Total income increased 14.13% to ₹85,942.34 million"
  vs "revenue from contracts with customers ₹81,415.38 million". Total income includes
  other income; revenue does not.
- **Units:** `₹8,142 Cr` vs `₹81,415.38 million` (see Case 1).

### Case 4 candidate — a real extraction failure I already hit
The **RBI annual report is a two-column layout**. Naive text extraction reads straight
across the page and welds the two columns into one line, producing sentences like:

> "closer to the target, largely due to easing input services exports and steady remittance inflows,"

That is two unrelated half-sentences glued together. Any fact extracted from it would be
grounded in text that does not actually exist in the document. This is a genuine,
reproducible failure and is a strong Case 4 — with a real fix (gutter detection) and an
honest note on what it still gets wrong (tables that legitimately span both columns).

Other real failure modes seen in the data:
- Negatives written as `(452)` and `₹(452) Cr` — read as positive if not handled.
- Numbers whose meaning lives in a footnote marker, e.g. `740 Mn` shipments with `(3)`
  pointing to "Includes Spoton's full year tonnage for FY22".
- Units declared once in a table caption ("in ₹ million, unless otherwise stated") and
  never repeated on the rows below.
- Page numbers inside the excerpts jump, because pages were cut from the originals.

---

## 4. Environment on this machine

| Thing | Status |
|---|---|
| Python | 3.13.7 |
| Node | v22.16.0 |
| Git | 2.55.0 — **the folder is not a git repo yet** |
| `gh` CLI | **Not installed** — GitHub repo has to be created in the browser |
| Docker | 28.3.2 |
| Already installed | fastapi, uvicorn, pdfplumber, pypdf, pypdfium2, streamlit, numpy, pandas, torch, openai, anthropic |
| Ollama | Installed, with `llama3`, `qwen3`, `llava`, `nomic-embed-text` pulled locally |
| API keys in env | **None found.** No OpenAI / Anthropic / Gemini key is set. |
| Internet | Working |

---

## 5. Decisions

Locked on 2026-09-08. Each row records the choice and the reason, so the trade-off is not
lost later.

| # | Decision | Choice | Why |
|---|---|---|---|
| D1 | Primary LLM | **Google Gemini `gemini-flash-lite-latest`** (free tier) | Free quota covers all ~511 pages, strong structured-JSON output, large context so a table can be sent with its caption intact. Keeps the project genuinely free to reproduce. |
| D2 | LLM portability | Provider-agnostic adapter: Gemini / OpenAI / Anthropic / Ollama | Whichever key is present is used. Falls back to local Ollama if none. The grader is never blocked by a missing key. |
| D3 | Interface | **FastAPI serving a plain HTML/JS single page** | One process, one command, no Node build. Full layout control for showing two facts, both quotes, the computed difference and the explanation side by side. |
| D4 | Fact scope | **Numeric facts + entity/state facts** | Covers the brief's own director example. Both kinds share one schema, so the extra cost is small. Narrative/opinion claims are deliberately excluded as not objectively comparable. |
| D5 | Demo coverage | **All 6 PDFs, with a cheap screening pass** | Proves generality across two unrelated domains, and unlocks the strongest genuine-contradiction case (three institutions, one economy, different numbers). |
| D6 | Storage | SQLite, single file | No server to install. Relations here are pairwise rows with attributes, which is a table, and the brief says a graph database is not the interesting part. |
| D7 | PDF parsing | PyMuPDF for layout + text, pdfplumber for tables | PyMuPDF is fast and gives word positions (needed for evidence highlighting). pdfplumber is better at ruled tables. Using both plays to each one's strength. |
| D8 | Embeddings | Ollama `nomic-embed-text`, already local | Free, offline, no download. Automatic fallback to character n-gram / TF-IDF similarity if Ollama is not running, so linking never hard-fails. |
| D9 | Verdict authority | Deterministic rules decide, LLM explains | Makes the reasoning auditable and reproducible. Model judgement is stored in a separate field so it is never mistaken for a rule result. |
| D10 | Grounding | Hard quote-verification gate | A claim whose quote is not literally in the PDF is rejected and logged. This is what makes "linked to evidence" a guarantee rather than a hope. |
| D11 | Secrets | `.env`, gitignored, with a committed `.env.example` | Assignment requires no credentials in the repo. |
| D12 | Reproducibility | Commit a prebuilt `knowledge.db` + JSON exports of the four cases | A grader with no API key can still start the server and click through every result. |
| D13 | Tests | pytest over the normalisers and the reconcile rules | These are the parts where correctness is objectively checkable; the LLM parts are not unit-testable, so effort goes where it pays. |
| D14 | Git | `git init` here, meaningful staged commits | `gh` is not installed, so the GitHub repo is created in the browser and pushed manually. |

---

## 6. Open items

| Item | Owner | Note |
|---|---|---|
| Gemini API key | **You** | Free, no card, from aistudio.google.com. Goes in `.env` as `GEMINI_API_KEY`. Blocks the real extraction run; everything else can be built without it. |
| GitHub repository | **You** | `gh` is not installed, so create an empty repo in the browser. I will hand you the two push commands. |
| Demo video | **You** | I cannot record. I will write a shot-by-shot script under 3 minutes with exact clicks. |
