# Fact Knowledge Layer

Upload PDFs. The system pulls out facts, ties every fact back to the exact words it came
from, and then works out which facts **agree**, which **disagree**, and which only *look*
like they disagree until you notice they cover different time periods, different scopes,
or different units.

Built for the Superjoin VIT 2026 Engineering Intern assignment.

> **Status: in development.** The plan is approved and documented in
> [`architecture.md`](architecture.md); decisions and their reasons are in
> [`context.md`](context.md). Sections marked _TODO_ below get filled in as the code lands.

---

## Setup and Run Instructions

_TODO — filled in once the code lands. The intended shape:_

```bash
# 1. install
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 2. add a key (optional - see "Running without a key" below)
cp .env.example .env
# put your free Gemini key in .env

# 3. run
uvicorn app.main:app --reload

# 4. open http://127.0.0.1:8000
```

Then drag a PDF onto the page, or process the bundled starter documents with:

```bash
python -m app.ingest starter-datasets/starter-datasets/delhivery/*.pdf
```

### Running without a key

A prebuilt results database is committed to the repo. If you start the server without any
API key, it loads that database and every screen works — you can browse the facts, the
evidence and all four cases. You only need a key to process **new** PDFs.

A free Gemini key from [aistudio.google.com](https://aistudio.google.com) needs no card and
its free quota is enough to process the entire starter dataset.

---

## Video Demo

_TODO — link goes here. Under 3 minutes, showing a PDF being processed and all four cases._

---

## Approach

Full detail is in [`architecture.md`](architecture.md). The short version:

A PDF is read with its layout intact, including detecting two-column pages so the columns
are not welded together. The text is split into blocks, and each block **remembers the
context above it** — its section headings, its table caption, and any units declared once
for a whole table. That inherited context is the thing that later lets the system tell a
real contradiction from an apparent one.

A cheap rule-based pass then decides which blocks could possibly contain a fact, so the
language model only sees the interesting parts of a 100-page report. The model turns those
blocks into structured claims, and **every claim must quote its source word-for-word**. The
quote is checked against the real page text; if it is not there, the claim is thrown out and
logged. That check is what makes "grounded in evidence" a guarantee rather than a hope.

Claims are normalised — crore and million converted to one base unit, `FY24` and
`year ended March 31, 2024` parsed to the same dates, `(452)` read as negative — and metric
names are merged into a registry that **starts empty and grows** as new kinds of facts turn
up. Claims about the same thing are then compared by **explicit rules**, not by asking the
model for an opinion. The rules compare named dimensions (period, unit, scope, basis,
vintage) and produce one of four verdicts plus a machine-readable trace of why. The model
is used afterwards to write the explanation in plain English, always constrained to the two
quotes and the computed difference.

_TODO: trade-offs, and the list of AI tools used._

---

## The four required cases

_TODO — each with its evidence and the system's reasoning, once the pipeline has run._

| # | Case | Status |
|---|------|--------|
| 1 | A fact corroborated across documents, expressed differently | _TODO_ |
| 2 | A genuine or likely contradiction | _TODO_ |
| 3 | An apparent contradiction explained by context | _TODO_ |
| 4 | An extraction or reasoning failure, and how it was handled | _TODO_ |

---

## Limitations and Next Steps

_TODO — written honestly once the system is running and its real weak spots are known._

---

## Additional Notes

The starter documents live in `starter-datasets/`. Two independent sets are included: three
Delhivery company filings, and three institutional reports on the Indian economy. The system
has no knowledge of either — no filenames, schemas or facts are hard-coded, and it is meant
to be pointed at any PDF.

Project documentation:

| File | What it is |
|---|---|
| [`README.md`](README.md) | This file. How to run it and what it does. |
| [`architecture.md`](architecture.md) | How the system works, and why it is shaped that way. |
| [`context.md`](context.md) | The running record: the task, what is in the data, every decision and its reason. |
