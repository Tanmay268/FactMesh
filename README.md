# Fact Knowledge Layer

Upload PDFs. The system pulls out facts, ties every fact back to the exact words it came
from, and then works out which facts **agree**, which **disagree**, and which only *look*
like they disagree until you notice they cover different time periods, different scopes,
or different units.

---

## Setup and Run Instructions

```bash
# 1. install
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 2. add a key (optional -- see "Running without a key" below)
cp .env.example .env
# put your free Gemini key in .env as GEMINI_API_KEY

# 3. run
uvicorn app.main:app --reload

# 4. open http://127.0.0.1:8000
```

Then drag a PDF onto the **Upload** panel, or process PDFs from the command line:

```bash
python -m app.ingest starter-datasets/starter-datasets/delhivery/*.pdf
```

Run the test suite (the normalisers and the rule engine -- the objectively checkable parts):

```bash
pytest
```

### Running without a key

A prebuilt results database (`data/knowledge.db`) is committed to the repo, built from a
real run across all six starter PDFs. Start the server without any API key and it loads
that database — every screen works, all four required cases are already in it, and you can
upload additional PDFs to browse how facts get added. A key is only needed to process **new**
PDFs yourself.

A free Gemini key from [aistudio.google.com](https://aistudio.google.com/apikey) needs no
card. One real constraint worth knowing about before you go looking for a key: **Google's
free tier gives each *model name* its own separate daily quota**, and they range from as low
as 20 requests/day to as much as 500/day, with no way to know which in advance. The adapter
(`app/llm/gemini.py`) handles this automatically — it falls over to the next model in a
fixed list the moment one runs out for the day, so a long ingest run does not just stop. If
every model on that list happens to be exhausted, the app is unusable with Gemini until the
next day's quota resets; add an `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` to `.env` instead, or
run a local [Ollama](https://ollama.com) server (`ollama pull qwen3` / `nomic-embed-text`) --
no key needed at all, just slower and noticeably weaker at pulling numbers out of dense
tables.

---

## Video Demo

**https://www.youtube.com/watch?v=yPCSo3ns2Q8**

---

## Approach

Full detail, including every trade-off and why, is in [`architecture.md`](architecture.md)
and [`context.md`](context.md). The short version:

**Parse.** A PDF is read with its layout intact via PyMuPDF, including detecting
two-column pages so the two columns are read one after the other rather than being welded
line-by-line into nonsense (found as a real bug on the RBI report — see Case 4 below).
pdfplumber pulls out ruled tables separately, since a table cell's meaning comes from its
row and column headers, not the words next to it on the page.

**Segment.** The text is split into blocks, and each block **remembers the context above
it** — the section headings it sits under, its table's caption and declared units, and
whether it is tagged standalone or consolidated. This inherited context is the single
biggest lever for telling a real contradiction from an apparent one later.

**Screen.** A cheap regex pass scores every block for whether it can plausibly hold a fact
(numbers, currency symbols, dates, period labels, appointment/resignation verbs). Only
blocks that clear the bar go to the model — across the whole 511-page starter dataset this
kept roughly a third to a half of blocks, which is most of why the run stayed affordable and
finished in about two and a half hours on a free API tier.

**Extract.** Fact-dense blocks are sent to the model **one page at a time**, with every
screened block on that page shown together — this is deliberate, because a table's header
row ("Q4 FY22 | Q4 FY23 | ...") and its data rows are frequently two separate blocks, not one
ruled object, and the model needs to see both to know which number belongs to which period.
Every returned claim carries a `quote`, and that quote is checked against the real page text
before the claim is kept — **if the quote is not found verbatim, the claim is thrown away
and logged**, never silently kept. Across the full run, 104 of 3,302 attempted claims (about
3%) were rejected this way.

**Normalise.** crore/million/billion/lakh convert to one base unit; `FY24`, `FY 2023-24`,
`year ended March 31, 2024`, `Q4 FY24` and `nine months ended December 31, 2021` all parse to
the same start/end dates (assuming the Indian April–March fiscal year, since every document
in scope is India-focused — see Limitations); `(452)` reads as negative; and metric labels
merge into a registry that starts empty and grows, so "Revenue from Operations" and "revenue
from services" become one metric without a hand-written list. Two guards stop that merging
from going wrong (found by testing on the real documents, not designed up front): a modifier
word like "margin" or "growth" that only one side has blocks a merge, and two different
all-caps acronyms (CPI vs WPI) block one too — both catch cases where plain string
similarity, and even embeddings, score a wrong pairing higher than a right one.

**Link.** Claims are grouped by (entity, canonical metric), and only claims in the same
group are ever compared. Adding a new document only links *its* claims against the existing
knowledge base, not the whole thing again — see "Brownie points" below.

**Reconcile.** For every candidate pair, explicit rules — never a model's opinion — compare
period, unit, basis and scope, and decide **CORROBORATES**, **CONTRADICTS**,
**RECONCILED_BY_CONTEXT** (naming the axis: time, scope, or units), or **UNRESOLVED**. A
full `rule_trace` is saved with every verdict, so the reasoning can be read without an LLM
call. A model is used only afterward, to phrase an explanation from that trace — and only
for the CONTRADICTS/RECONCILED_BY_CONTEXT verdicts, where the extra nuance is worth the
cost; the bulk CORROBORATES/UNRESOLVED cases get a fast, deterministic template built from
the same trace. This split is also what kept the full run affordable: with ~2,500 candidate
pairs found across six documents, paying for a model call on every one of them would have
been the dominant cost for very little benefit.

### Important decisions and trade-offs

- **SQLite over a graph database.** The assignment says explicitly that a graph database is
  not the interesting part of this problem, and relations here are pairwise rows with rich
  attributes (verdict, axis, trace, explanation) — that is a table. SQLite also means the
  grader runs one `uvicorn` command with nothing else to install.
- **Rules decide, the model explains.** Every verdict is reproducible from
  `dimension_diff`/`rule_trace` alone. This was the design from the start, and it held up —
  when real data produced results I didn't expect (see below), the trace made it possible to
  tell whether the *rule* was wrong or the *data feeding it* was wrong, rather than just
  getting a different-sounding paragraph from the model on a re-run.
- **Provider-agnostic LLM adapter, used for real, not just in theory.** Gemini's free tier
  turned out to have per-model daily quotas as low as 20 requests, discovered mid-build by
  running out of them repeatedly. The four showcase relations' explanations in this
  submission were ultimately generated by the **local Ollama fallback** (`qwen3:8b`), not
  Gemini, because every Gemini model tried had run dry for the day by the time I got there —
  a real demonstration of the fallback chain, not a hypothetical one.
- **AI tools used.** Claude (Opus 5 for planning and architecture, Sonnet 5 for
  implementation) built this project end-to-end in a pair-programming style — planning,
  writing the pipeline, running it against the real starter PDFs, diagnosing failures from
  the actual output, and fixing them. Gemini (`gemini-3.1-flash-lite-preview`, arrived at via
  the automatic fallover above) is the extraction model used for the committed database.
  Ollama (`qwen3:8b`, local) generated the four showcase explanations quoted below and is the
  no-key fallback path. Every fix in this repo's git history was driven by something the
  system actually got wrong on real data, not a hypothetical edge case.

---

## The four required cases

All four below are **real relations pulled from the committed database**, not constructed
examples — every quote, page number and relation ID can be looked up in the running app
(Relations tab) or the raw SQLite file. `find_showcase.py` in `scripts/` is the query tool
that surfaced these from the ~2,500 relations in a real run.

### 1. A fact corroborated across documents, expressed differently

**Verdict: CORROBORATES.** India's foreign exchange reserves in September 2024, reported by
two different institutions:

- **IMF Article IV Report, p.12:** *"...from $706 billion in September 2024"*
- **Economic Survey 2024-25, p.31:** *"USD 704.9 billion in September 2024"*

Both parse to the same subject (India), metric (foreign exchange reserves), unit (USD
billion) and period (September 2024). The values differ by 0.16% — inside the system's 1%
rounding tolerance — so the rule engine marks this **CORROBORATES**.

> *"Both facts refer to India's foreign exchange reserves in September 2024, with values
> extremely close (706 vs. 704.9 billion). The small difference is likely due to rounding,
> and the similarity in numbers supports the same overall figure."*

### 2. A genuine or likely contradiction

**Verdict: CONTRADICTS.** India's real GDP growth for the same fiscal year, from two
institutions using the same period label:

- **IMF Article IV Report, p.10:** *"India's real GDP grew by 6.5 percent in FY2024/25."*
- **Economic Survey 2024-25, p.4:** *"India's real GDP is estimated to grow by 6.4 per cent
  in FY25"*

Same subject, same metric, same period (`FY2024/25` and `FY25` both parse to 1 Apr 2024 – 31
Mar 2025), same units — but the values genuinely differ (6.5% vs 6.4%). No qualifier
(basis/segment) distinguishes them, so the rule engine marks this **CONTRADICTS** rather than
reconciling it away.

> *"Both facts refer to the same fiscal period (FY2024/25 vs. FY25, which are effectively the
> same timeframe) but report different real GDP growth rates (6.5% vs. 6.4%). Since they
> share the same subject, metric, and scope but provide conflicting numerical values, the
> difference is genuine and not explained by context, leading to a contradiction."*

*(One caveat worth being upfront about: FY25 growth is a moving target across an "advance
estimate" → "provisional estimate" → final-estimate revision cycle in Indian statistics, and
neither document's claim carries that vintage as an explicit qualifier in this run, since it
was rarely stated as plainly as the period itself. If it had been captured, this might instead
be a Case-3-style RECONCILED_BY_CONTEXT on a `vintage` axis. Flagged honestly rather than
overstated — it still is a genuine numeric disagreement as stated.)*

### 3. An apparent contradiction explained by context

Two clean examples turned up, one per axis:

**3a — axis: time.** The exact scenario the assignment's own brief describes:

- **Prospectus, 2022, p.88:** *"Suvir Suren Sujan is a Non-Executive Nominee Director of our
  Company"* — status: active.
- **Annual Report FY24, p.33:** *"Mr. Suvir Suren Sujan, Non-Executive Director, resigned
  from the Board with effect from August 24, 2023."* — status: resigned.

The system infers each document's own "as of" date from its own claims (2021-12-31 for the
prospectus, 2024-12-31 for the annual report) and, seeing the documents are dated
differently, reconciles rather than flags a contradiction:

> *"Fact A describes Suvir Suren Sujan as a Non-Executive Nominee Director in 2021, while
> Fact B states he resigned in 2023. The documents from 2021 and 2024 show his status changed
> over time, so the apparent contradiction is resolved by the timeline — his resignation in
> 2023 ended his active role, aligning with the 2024 document."*

**3b — axis: scope.** Same document, same page, same period, two different numbers:

- **Annual Report FY24, p.22:** *"FY24 stood at ₹ 81,415.38 million"* (basis: consolidated)
- **Annual Report FY24, p.22:** *"stood at ₹ 74,540.82 million as against ₹66,586.61 million
  for FY23"* (basis: standalone)

> *"The two facts are reconciled by context because they refer to different reporting bases:
> Fact A uses consolidated financials (including subsidiaries) while Fact B uses standalone
> figures (only the parent company). This explains the discrepancy in revenue numbers for the
> same fiscal year."*

### 4. An extraction or reasoning failure, and how it was handled

**Failure found early: two-column pages read as one column.** PyMuPDF's raw block order on
the RBI Annual Report's two-column pages interleaved the left and right columns by vertical
position, producing text like:

> *"closer to the target, largely due to easing input services exports and steady remittance
> inflows,"*

— the left column's sentence about inflation targets, welded mid-sentence to the right
column's sentence about the current account deficit. **Fixed** with column detection in
`app/parsing/pdf_reader.py`: pages where blocks cluster into a clear left group and a right
group are read left-column-top-to-bottom, then right-column-top-to-bottom. **Still not
perfect**: a block that legitimately spans both columns (a wide table dropped into a
two-column page) would be mis-ordered by this same logic, since the detector has no per-block
"this one is different" signal — a known, documented limitation, not a silent one.

**Failure caught by design, not fixed: the quote-verification gate rejecting real work.** 104
claims were rejected across the run for failing the verbatim-quote check — most correctly
(the model paraphrasing rather than quoting), but inspecting them turned up a case worth
being honest about: on the ESG disclosures page, the model reported *"reduced ~20% from
229.1 gCO2e/tonne-kilometre in FY23 to 184 gCO2e/tonne-kilometre in FY24"* — a real
calculation (`(229.1-184)/229.1 ≈ 20%`) built by combining two numbers that *were* both
genuinely on the page, just not adjacent as a single quotable sentence. The gate correctly
rejected it (it is not a verbatim quote), which is the right call for grounding, but it
means a true, checkable fact was lost rather than kept with a note that it was
derived — a real trade-off between strict grounding and recall that I'd improve by allowing
a "derived from these two grounded quotes" claim type instead of an all-or-nothing gate.

**Reasoning gap found while picking these examples, not yet fixed:** the same annual report
independently restates one person's departure as `"resigned"` in one section and
`"ceased to be associated with the Company ... due to resignation"` in another. Both describe
the same event, but the reconciliation rule compares `state_value` strings exactly, so this
surfaces as a same-document **CONTRADICTS** rather than a corroboration — a synonym-blindness
gap in the entity-state comparison, not a time or scope issue the current rules know how to
name. Left in the committed database on purpose rather than special-cased away, because it is
a genuine and instructive limitation: **Next step** would be a small canonical vocabulary for
entity-state values (resigned/ceased/stepped down → one state) before falling back to a raw
string match.

---

## Limitations and Next Steps

**What doesn't work well yet:**
- Metric matching is the weakest link. It merges genuine paraphrases most of the time, and
  two targeted guards (a modifier-word check, an acronym check — see Approach) catch the
  specific wrong-merge patterns found while testing, but it is not a general solution;
  1,248 distinct metrics were registered across the run, and some are almost certainly
  unmerged duplicates that a smarter (embedding-based, properly tuned) matcher would catch.
- Entity-state comparison is exact-string on the state value (`"resigned"` vs `"ceased"`,
  see Case 4) — it needs a small canonical vocabulary, not raw equality.
- The fiscal-year parser assumes the Indian April–March convention everywhere, since every
  document in scope is India-focused. A document using a different fiscal calendar would be
  silently mis-parsed — this is a real gap, not just a caveat, and the parser has no way to
  detect it is wrong on its own.
- Table geometry is imperfect: a header row and its data rows are frequently separate blocks
  (see Approach), and while sending them to the model together mostly works, a handful of
  the `quote_not_found` rejections trace back to the model reading across that gap
  incorrectly.
- The bounding box stored per claim is its whole source block's box, not a tight box around
  the specific quote — evidence highlighting in the UI is closer to "this paragraph" than
  "this exact phrase."

**What I'd build next**, roughly in priority order:
1. A canonical vocabulary for entity-state values, closing the Case 4 gap above.
2. A "derived fact" claim type — a number computed from two grounded quotes, kept with both
   source quotes attached, instead of being an all-or-nothing verbatim match.
3. Embedding-based metric matching (with the two guards kept as a safety net on top, since
   testing showed embeddings alone don't reliably separate a metric from its own margin/
   ratio either), to cut down the metric count and catch more true corroborations.
4. Detecting which fiscal-year convention a document actually uses, rather than assuming one.
5. A tighter per-quote bounding box for evidence highlighting, using word-level positions
   already captured during parsing but not yet threaded through to the stored claim.

---

## Additional Notes

The starter documents live in `starter-datasets/`. Two independent sets: three Delhivery
company filings, three institutional reports on the Indian economy. The system has no
knowledge of either built in — no filenames, schemas or facts are hard-coded — and it is
meant to be pointed at any PDF; the committed database is simply the result of one real run
across all six.

**Reproducing this run:** `python -m app.ingest <paths...>` against all six starter PDFs
took about 2.5 hours end to end (extraction is throttled to respect the free tier's
requests-per-minute limit) and produced 3,198 facts and 2,510 relations from 511 pages.
Re-running is a no-op for files already ingested (matched by content hash) — see
`app/ingest.py`.

Project documentation:

| File | What it is |
|---|---|
| [`README.md`](README.md) | This file. How to run it and what it does. |
| [`architecture.md`](architecture.md) | How the system works, and why it is shaped that way. |
| [`context.md`](context.md) | The running record: the task, what is in the data, every decision and its reason, kept up to date as the build happened. |
