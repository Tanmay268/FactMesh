# Demo Video Script (target: under 3 minutes)

Shot-by-shot script, filled in with the exact relations from the real run (see README.md
"The four required cases" for the full quotes and reasoning — this script only summarises
what to click and say). Record with the app running at `http://127.0.0.1:8000`, loaded from
the committed `data/knowledge.db`.

---

### 0:00 – 0:20 — Intro + upload a PDF

1. Open the app. Say: "This is a Fact Knowledge Layer — upload any PDF, it extracts facts,
   links them to evidence, and works out which facts agree, disagree, or only look like they
   disagree. This database already has six real filings processed — 3,198 facts, 2,510
   relations — but let me show it accepting a new one live."
2. Drag the Q4 FY24 earnings presentation (or any starter PDF) onto the **Upload** panel.
   Since it is already ingested (matched by content hash), it will report "already
   ingested" almost instantly — mention that re-uploading is a no-op, and that a fresh PDF
   would take a few minutes per hundred pages.
3. Point at the stat tiles (documents / facts / relations / issues).

### 0:20 – 0:55 — Case 1: corroboration across institutions

1. **Relations** tab → filter **Corroborates**.
2. Open the India foreign-exchange-reserves relation: IMF says "$706 billion" (p.12),
   Economic Survey says "USD 704.9 billion" (p.31), both for September 2024.
3. Read the explanation aloud: *"...values extremely close (706 vs. 704.9 billion). The
   small difference is likely due to rounding..."*
4. Say: "Two different institutions, independently confirming the same figure — the system
   normalised both to the same unit and period before comparing."

### 0:55 – 1:35 — Case 2: a genuine contradiction

1. Filter to **Contradicts**.
2. Open the India real-GDP-growth relation: IMF says 6.5% for FY2024/25 (p.10), Economic
   Survey says 6.4% for FY25 (p.4).
3. Read the explanation: *"...share the same subject, metric, and scope but provide
   conflicting numerical values, the difference is genuine..."*
4. Say: "Same period, same metric, no reconciling context found — flagged as a real
   disagreement rather than silently averaged or picked."

### 1:35 – 2:15 — Case 3: apparent contradictions explained by context

1. Filter to **Reconciled by context**.
2. Open the **Suvir Suren Sujan** relation (axis: time): active Non-Executive Nominee
   Director per the 2022 prospectus, resigned per the FY24 annual report.
3. Read the explanation: *"...his resignation in 2023 ended his active role, aligning with
   the 2024 document."*
4. Say: "This is the exact scenario the assignment describes — a director active in one
   document, resigned in a later one. The system worked out which document was dated later
   and explained the gap instead of flagging it as a contradiction."
5. Quickly show the second one too (axis: scope) — Delhivery's FY24 revenue stated as both
   ₹81,415.38M (consolidated) and ₹74,540.82M (standalone) on the same page: *"...refer to
   different reporting bases..."*

### 2:15 – 2:50 — Case 4: an extraction failure, handled honestly

1. Say: "Two failures worth showing, both real, both found by running this on the actual
   PDFs."
2. First: describe (or show, if you have the RBI PDF page open) the two-column welding bug
   — read the garbled sentence from README.md's Case 4 section, then say it was fixed with
   column detection, but a table spanning both columns would still trip it up.
3. Second: click the **Issues** tab, point at a `quote_not_found` entry — the ESG
   "reduced ~20%" example is a good one to show. Say: "The model built this number by
   combining two real figures on the page, but couldn't quote it verbatim, so the system
   rejected it rather than keep an ungrounded claim. That's the right call for grounding,
   but it's also a real fact that got lost — a trade-off I'd improve with a 'derived fact'
   claim type that keeps both source quotes."

### 2:50 – 3:00 — Close

1. Quick look at the **Schema** tab: "The metric list isn't hard-coded — it grew to over a
   thousand entries on its own as this ran across six very different documents."
2. End.

---

## Notes for recording

- Keep each relation card open for 3–5 seconds minimum so a viewer can actually read the
  quotes.
- If short on time, cut the second Case 3 example (3b) rather than rushing case 4 — the
  brief only requires one example per case.
- A voiceover is not required by the brief, but reading the explanations aloud (rather than
  silent clicking) makes the four cases much easier to follow.
