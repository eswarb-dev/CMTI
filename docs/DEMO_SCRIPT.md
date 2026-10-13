# Demo Script — Five-Minute Manufacturing Engineering Copilot Walkthrough

> **Prototype only.** All data is synthetic. Do not deploy publicly or connect to real factory systems.

## Before the Demo

Ensure the application is running:

```powershell
# Option A: Docker Compose (full stack)
docker compose up --build -d
docker compose exec backend python -m app.cli seed-demo-data

# Option B: Local development
cd backend
docker compose up postgres -d
alembic upgrade head
python -m app.cli seed-demo-data
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# In a second terminal:
cd frontend
npm run dev
```

Open `http://localhost:80` (Docker) or `http://localhost:5173` (local) in your browser.

---

## Minute 0:00–0:45 — Dashboard Overview

1. **Point out the demo banner** at the top: "Demo - Synthetic manufacturing data."
2. **Machine selector**: Show CNC-M04 (primary, degrading) and CNC-M02 (healthy comparison).
3. **Key metrics**: Highlight roughness mean, OOS rate, diameter Ppk, trend delta, overdue tool count, sample count.
4. **Charts**: Show the roughness-by-batch trend line with the red spec limit at 1.6 um Ra. Point out the upward trend on CNC-M04.
5. **Batch summaries table**: Point out OOS cells highlighted in red and overdue tool usage cells.
6. **Ranked hypotheses**: Show the hypothesis cards with evidence links and scores.

**Key message:** "All values are computed from seeded measurements. Nothing is hardcoded."

---

## Minute 0:45–1:30 — Engineering Question

1. Click the **Copilot** tab.
2. Show the suggested demo questions. Select or type:
   > "Why is surface roughness Ra increasing on CNC-M04?"
3. Point out the advisory notice: "All associations are hypotheses, not proven causes."
4. Click **Run Investigation**.

---

## Minute 1:30–2:30 — Execution and Evidence

1. **Execution progress**: Watch the workflow steps complete (validate, retrieve, tools, assess).
2. **Structured assessment**: Show the summary, hypotheses, supporting evidence, and contradictory evidence sections.
3. **Computed analytics**: Expand the roughness_summary, tool_usage, and diameter_performance cards. Point out:
   - Sample count is computed, not hardcoded
   - Limitations are displayed for each tool
   - Units are shown
4. **Evidence panel**: Show the retrieved document cards with citation chips.
5. **Citation tooltip**: Click a citation chip to expand the document snippet, source location, and approval state.
6. **Warnings**: Point out the "untrusted evidence only" warning.

**Key message:** "The workflow retrieves approved evidence, runs deterministic analytics, and generates an advisory assessment. It never executes arbitrary commands."

---

## Minute 2:30–3:15 — Review Decision

1. Click the **Investigations** tab.
2. Select the investigation from the list. Point out the review state badge ("draft") and version number.
3. **Download PDF Report** button — click it to show the PDF opens in a new tab. (We'll come back to this.)
4. **Review form**:
   - Enter a reviewer name (e.g., "Jane Engineer")
   - Select "pending_review" as target state
   - Enter a comment (e.g., "Submitted for manufacturing engineer review.")
   - Click **Submit Review**
5. Point out:
   - Review state updated to "pending_review"
   - Version incremented to 2
   - Review event appears in the history with "unverified" identity notice
6. Submit another review to "approved" state. Show version increments to 3.

**Key message:** "Review identity is unverified demonstration input. Approving does not issue machine commands, release production, or close real enterprise records."

---

## Minute 3:15–4:00 — PDF Export

1. Click **Download PDF Report** on the approved investigation.
2. The PDF opens in a new tab. Walk through the pages:
   - **Page 1**: Synthetic data notice, reviewer identity notice, investigation scope (machine, part, characteristic, time range)
   - **Engineer question** and **evidence-backed findings/hypotheses**
   - **Deterministic analytics**: Methods, computed values, limitations
   - **Charts** (if embedded) or chart description
   - **Recommendations** and **unresolved risks**
   - **Document citations and revisions** table with citation IDs, document IDs, revisions, approval state
   - **Execution events** table
   - **Review status and history** table with all review events
   - **Footer notices**: Synthetic data + must not issue machine commands

3. Point out:
   - Wrapped table cells, no clipped content
   - Page numbers on every page
   - Repeated table headers on multi-page tables
   - Safe margins throughout

---

## Minute 4:00–4:30 — Evidence Retrieval

1. Click the **Evidence** tab.
2. Show the hybrid retrieval description: semantic + lexical + exact identifier matching with reciprocal rank fusion.
3. Enter a query like "surface roughness Ra inspection limits CNC-M04".
4. Click **Test Retrieval**.
5. Show the returned evidence cards with citation chips, document IDs, revisions, and approval states.

**Key message:** "Retrieved documents are evidence only. They cannot authorize tool calls, SQL, or policy changes."

---

## Minute 4:30–5:00 — Summary and Boundaries

Summarize what was demonstrated:

| Feature | Status |
|---------|--------|
| Dashboard analytics | Live — computed from seeded measurements |
| Investigation workflow | Live — advisory, human-review oriented |
| Evidence retrieval | Live — hybrid semantic + lexical |
| Deterministic analytics | Live — Pp/Ppk, trends, OOS rate |
| Review decisions | Live — server-enforced state machine |
| PDF report export | Live — reportlab-generated |
| LLM assessment | Deferred — optional Groq provider, disabled by default |
| Real manufacturing data | Not included — all synthetic |
| Authentication | Not included — prototype demo only |
| Production deployment | Not included — do not deploy publicly |

**Key message:** "This is a prototype demonstrating the investigation workflow, analytics, and review process. The complete investigation works without hardcoded conclusions. Citations resolve, analytics match tests, review state persists, and PDF pages have no clipped or overlapping content."

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Backend not responding | Check `docker compose ps` or restart uvicorn |
| "No analytics data" | Run `python -m app.cli seed-demo-data` |
| Frontend blank | Ensure backend is on port 8000, check browser console |
| PDF not opening | Check backend logs, ensure reportlab is installed |
| PostgreSQL error | Run `docker compose up postgres -d` |
