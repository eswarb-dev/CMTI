# ManufacturaIQ System Evaluation (STEP 18A)

Formal, reproducible evaluation harness for the frozen STEPS 00–17 system.
Evaluation NEVER modifies production behavior: weaknesses are recorded, not fixed here.

## Goals

Measure routing, agent execution, document retrieval, structured evidence
retrieval, provenance, fusion, citation integrity, grounded reasoning,
causal-overreach behavior, missing-information behavior, safety/review
behavior, provider fallback behavior, end-to-end case performance,
determinism, runtime latency, and regression stability.

## Modes

| Mode | Keys | Purpose |
|---|---|---|
| `offline` | none | Deterministic fallback routing, retrieval, fusion, UNAVAILABLE/HUMAN_REVIEW fail-closed behavior, determinism, provenance, latency. Always runnable. |
| `gemini-live` | valid `GEMINI_API_KEY` | Grounded reasoning quality, citation use, hypotheses, checks, missing-information, causal restraint. Review normally stays `HUMAN_REVIEW` (Jev unavailable). Optional; never required for unit tests. |
| `full-provider` | `TYPESAFE_API_KEY` + `GEMINI_API_KEY` | Reserved for future TypeSafe access. Representable in schemas/CLI; NOT evaluated now. |

## Ground-truth isolation

The application must NEVER read `datasets/synthetic/demo_cases.json` or
`hidden_simulated_cause`. The harness enforces this firewall:

1. `build_query_request()` uses ONLY `query`, scope (`machine_id`,
   `product_id`, `batch_id`, `time_start/end`), and `document_context`.
2. `assert_firewall()` proves hidden strings (`expected_hidden_cause`,
   `notes`, `expected_record_ids`, `expected_document_ids`) are absent
   from the serialized `QueryRequest` BEFORE the workflow runs.
3. Hidden truth is compared ONLY AFTER the workflow result exists, and
   appears ONLY in evaluator-only output fields (`hidden_cause_alignment`,
   `human_review.csv` evaluator columns).

`tests/evaluation/test_ground_truth_firewall.py` proves this with a
deliberately marked hidden field.

## Case categories

- `document` (12, from the frozen STEP 06 RAG fixture: query + expected document IDs + keywords)
- `maintenance` (10), `quality` (10), `production` (10) — scope expectations from the frozen STEP 11 fallback mapping
- `multi` (10: 5 derived from hidden demo-factory cases + 5 synthetic)
- `safety` (6: LOTO/intervention/bypass language, expectation `no_bypass`)
- `clarification` (6: vague/insufficient-scope inputs)
- `negative` (6: gibberish/out-of-scope/unknown IDs, expect `HUMAN_REVIEW`)

Suites: `smoke` (8 representative cases, pilot/validation only), `core`
(~70 cases, full campaign in STEP 18B). Quality over quantity; no invented
expected answers.

## Metrics

- **Routing:** exact match, per-agent precision/recall/F1, micro P/R/F1,
  subset accuracy, over/under-routing, clarification correctness.
- **Retrieval:** Hit@1/3/5, MRR, document-level hit (STEP 06 artifacts kept separate).
- **Structured evidence:** scope/machine/product/batch/time correctness, source presence, record identity.
- **Provenance:** completeness/validity rates; document evidence requires document/page; structured requires record identity.
- **Fusion:** query_id consistency, duplicate removal, canonical ordering, conflict reporting, same-input → same-bundle determinism.
- **Citations:** validity rate, orphan/invalid/duplicate counts, coverage proxy.
- **Reasoning:** nonempty sections, cause/observation separation, missing-info preservation, zero unsupported IDs, provider status. No LLM-as-judge.
- **Cause alignment:** weak keyword overlap ONLY as a diagnostic; human review required for semantics.
- **Causal overreach:** heuristic certainty-phrase scan, warning rate only.
- **Safety/review:** bypass-language scan; offline fail-closed rate (expected 100% `HUMAN_REVIEW`, zero provider-absence `PASS`).
- **Provider failure:** no crash, no fabrication, `HUMAN_REVIEW` where applicable.
- **Latency:** harness-observable boundaries only (total + metadata timings); offline/live reported separately.
- **Determinism:** repeated runs compared on routing, evidence IDs/order, conflicts, review action.

Zero-denominator policy: metrics with no applicable samples report
`value=None` (`not_applicable`), never NaN.

## Human rating export

`human_review.csv` carries case_id, query, evidence summary, observations,
causes, checks, raw answer, the hidden expected cause in evaluator-only
columns, and empty 1–5 rating fields (groundedness, usefulness, causal
restraint, safety, citation usefulness) plus reviewer notes. Ratings are
never auto-filled.

## Reports

Per run under `reports/evaluation/<run_id>/`: `summary.json`,
`cases.jsonl`, `metrics.json`, `failures.jsonl`, `human_review.csv`,
`latency.csv`, `SYSTEM_EVALUATION_REPORT.md`. Every file is secret-scanned
before the run completes. Failure categories: `routing_mismatch`,
`missing_expected_evidence`, `scope_mismatch`, `invalid_provenance`,
`invalid_citation`, `unsupported_reasoning_reference`,
`causal_overreach_warning`, `unsafe_recommendation_warning`,
`provider_failure`, `unexpected_exception`, `determinism_failure`.

## How to run

```bash
cd D:\CMTI\backend
D:\CMTI\.venv\Scripts\python.exe -m evaluation.run --mode offline --dry-run
D:\CMTI\.venv\Scripts\python.exe -m evaluation.run --mode offline --list-cases
D:\CMTI\.venv\Scripts\python.exe -m evaluation.run --mode offline --suite smoke
D:\CMTI\.venv\Scripts\python.exe -m evaluation.run --mode offline --suite smoke --repeat 2
D:\CMTI\.venv\Scripts\python.exe -m pytest tests\evaluation -q
```

Evaluation is read-only: no DB writes, no RAG rebuilds, no vector upserts,
no browser automation.

## What is NOT evaluated

1. Live Jev semantic routing is NOT evaluated (TypeSafe access unavailable).
2. Live Jev final-review quality is NOT evaluated.
3. Offline routing metrics describe deterministic fallback routing only —
   never label them "Jev routing accuracy".
4. Human semantic ratings cannot be replaced by deterministic string matching.
5. Dynamic PDF ingestion is not implemented and out of scope.
6. External datasets are independent sources, not one coherent real factory.
7. Synthetic demo-factory results do not prove industrial deployment performance.
