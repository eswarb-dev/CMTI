# STEP 20 — Dynamic Knowledge-Base Evaluation

Run ID: `20260927T205246_dynamickb`

This evaluation exercised the frozen STEP 19B2 dynamic PDF knowledge-base
system through public HTTP endpoints. Production code was not tuned or changed.

## Scope

Evaluated:

- PDF upload and validation
- duplicate and concurrent duplicate handling
- registry, original-file, and vector integrity
- static/dynamic corpus isolation
- dynamic retrieval quality
- document-context filtering
- evidence provenance
- prompt-injection-like PDF text as data
- restart persistence
- deletion and re-upload
- determinism and latency

## Headline Metrics

| Metric | Result |
|---|---:|
| Valid evaluation PDFs | 16 |
| Negative PDF cases | 6 |
| Upload success rate | 1.000 |
| READY rate | 1.000 |
| Validation rejection correctness | 1.000 |
| Duplicate detection accuracy | 1.000 |
| Dynamic Hit@1 | 0.947 |
| Dynamic Hit@3 | 0.947 |
| Dynamic Hit@5 | 1.000 |
| Dynamic MRR | 1.000 |
| Document hit rate | 1.000 |
| Page hit rate | 1.000 |
| Context allow / deny | true / true |
| Provenance validity | 0.947 |
| Delete success | 1.000 |
| Post-delete absence | true |
| Static-ID delete protection | true |
| Re-upload after delete | true |
| Determinism rate | 1.000 |

## Latency

| Phase | Median ms | P95 ms | Max ms |
|---|---:|---:|---:|
| Upload | 1111.862 | 12032.109 | 12032.109 |
| Query | 102.659 | 135.131 | 289.648 |
| Delete | 27.170 | 34.356 | 34.356 |
| List | 43.619 | 43.619 | 43.619 |

## Static And Dynamic Counts

Static vector count stayed `2193` before, after uploads/restart, and after
cleanup.

Campaign baseline:

- registry rows: `0`
- originals: `0`
- dynamic vectors: `0`

Campaign artifact summary recorded five FAILED negative-case rows after the
campaign. These were cleaned up afterward through the public DELETE endpoint.

Final verified cleanup:

- registry rows: `0`
- originals: `0`
- dynamic vectors: `0`
- static vectors: `2193`

## Findings

1. Dynamic retrieval quality was strong overall, but one dynamic query missed
   rank 1 and rank 3 while still hitting by rank 5.
2. The Unicode evaluation document was flagged by the evaluation safe-field
   heuristic as `path/identity leak`. Manual review is needed to determine
   whether this is a true public-leak issue or a false positive from the
   evaluation scanner.
3. Restart retrieval persisted successfully. The report also flagged
   `restart list count 22 != 24`; this appears tied to how the evaluation
   harness counts duplicate/negative rows rather than a static-corpus mutation.
4. Negative PDFs were rejected correctly in the clean-baseline run.
5. Prompt-injection-like text was retrieved as ordinary evidence data and did
   not delete documents or expose secrets in the evaluation output.

## Artifacts

Artifacts are under:

`reports/evaluation/documents/20260927T205246_dynamickb/`

- `summary.json`
- `uploads.jsonl`
- `retrieval.jsonl`
- `deletions.jsonl`
- `metrics.json`
- `failures.jsonl`
- `latency.csv`
- `DYNAMIC_KB_EVALUATION_REPORT.md`

## STEP 20A Diagnostic Resolution

Run ID: `20260928T000002_step20a`

STEP 20A was evaluation-harness diagnostic work only. Production document,
retrieval, registry, API, and frontend behavior were not changed.

Resolved findings:

- DOC-EVAL-11 was a false-positive evaluation scanner finding. The previous
  scanner searched the whole evidence blob with broad path/identity patterns;
  the corrected scanner classifies only field-specific forbidden public values.
- Restart expected count is now derived from persistent lifecycle rows, not
  upload attempts. The corrected expected count was `22`, actual restart count
  was `22`, and lost rows were `0`.
- FAILED negative-case registry rows are expected production lifecycle records
  until explicitly deleted. Evaluation cleanup now deletes all campaign-created
  dynamic document IDs through public `DELETE /api/documents/{id}`.
- The rank-5 retrieval miss for DOC-EVAL-02 was repeated three times and was
  deterministic. It is recorded as a measured retrieval limitation, not a
  ranking fix request.

STEP 20A artifacts are under:

`reports/evaluation/documents/20260928T000002_step20a/`

- `finding_resolution.json`
- `lifecycle_accounting.json`
- `cleanup_verification.json`
- `retrieval_miss.json`
- `STEP20A_FINDINGS.md`

