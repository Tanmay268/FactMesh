# Demo Video Script (target: under 3 minutes)

This is a shot-by-shot script for recording the required demo video. Follow it in
order; each shot names exactly what to click and roughly how long to spend on it.
Record your screen with the app running at `http://127.0.0.1:8000`.

_This script is written from the plan and will be tightened once the real ingestion
run finishes and the exact relation IDs/pages for each showcase case are known — see
the placeholders marked `[FILL IN]`._

---

### 0:00 – 0:20 — Upload a PDF (the "accepts new PDFs" requirement)

1. Open the app. Say (or caption): "This is a Fact Knowledge Layer — upload any PDF,
   it extracts facts, links them to evidence, and works out which facts agree,
   disagree, or only look like they disagree."
2. Drag one of the starter PDFs onto the **Upload** panel (pick a short one, e.g. the
   Q4 FY24 earnings presentation, so the on-screen wait is short — mention that the
   full 511-page run across all six documents was done ahead of time and is already
   loaded).
3. Point at the stat tiles updating (documents / facts / relations / issues).

### 0:20 – 0:55 — Case 1: a fact corroborated across documents

1. Click the **Relations** tab, filter to **Corroborates**.
2. Open the card showing: `[FILL IN: e.g. Delhivery FY24 revenue — ₹8,142 Cr (earnings
   deck) vs ₹81,415.38 million (annual report)]`.
3. Point at both quotes side by side, and read the one-line explanation out loud.
4. Say: "Same fact, different units, different wording, different document — the
   system normalises both to the same base unit and confirms they match."

### 0:55 – 1:35 — Case 2: a genuine or likely contradiction

1. Filter **Relations** to **Contradicts**.
2. Open: `[FILL IN: e.g. two different institutions stating a different FY25 GDP
   growth figure for the same period]` — or the director-status case if that turned
   out to be the cleaner example.
3. Point at both quotes, the computed relative difference, and the explanation.
4. Say: "Same period, same entity, no reconciling context found — the system flags
   this as a real disagreement rather than silently picking one."

### 1:35 – 2:15 — Case 3: an apparent contradiction explained by context

1. Filter **Relations** to **Reconciled by context**.
2. Open: `[FILL IN: e.g. Delhivery FY24 revenue — ₹74,540.82 million (standalone) vs
   ₹81,415.38 million (consolidated), same page of the same document]`.
3. Point at the `axis: scope` tag and read the explanation.
4. Say: "These look like a contradiction until you notice one is standalone and the
   other consolidated — the system caught that from the table's own labelling and
   explains the difference instead of just reporting two different numbers."

### 2:15 – 2:45 — Case 4: an extraction/reasoning failure, honestly handled

1. Click the **Issues** tab.
2. Point at the two-column layout issue: show the raw welded text
   (`"closer to the target, largely due to easing input services exports..."`) either
   as a logged issue or by briefly showing the PDF page (RBI Annual Report, page with
   the two-column layout) next to the cleanly-separated result the system now
   produces after column detection.
3. Say: "This is a real extraction failure I found early on — two unrelated columns
   of text getting welded into one nonsense sentence. I fixed it with column
   detection, but here's a case it still doesn't handle perfectly: `[FILL IN: e.g. a
   table that legitimately spans both columns]` — and here's what I'd do next."

### 2:45 – 3:00 — Close

1. Quick look at the **Schema** tab: "The metric list isn't hard-coded — it grows as
   new kinds of facts are found, and this same pipeline runs on any PDF, not just
   these six."
2. End.

---

## Notes for recording

- Keep each relation card open for 3–5 seconds minimum so a viewer can actually read
  the quotes — don't rush past them.
- If OBS/screen recorder adds its own timer, use that to stay under 3:00; trim in
  editing if you run long rather than talking faster.
- A voiceover is not required by the brief, but captions or a spoken walkthrough make
  the four cases much easier to follow than silent clicking.
