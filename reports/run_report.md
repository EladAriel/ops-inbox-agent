# Pipeline run report

**When:** 2026-09-05  
**Command:** `TRIAGE_MOCK_APPROVE=all python3 -m starter.pipeline`  
**Input:** `requests.jsonl` (40 requests)  
**Output:** `results.jsonl` (40 audit records)

## Summary

| Metric | Value |
| --- | --- |
| Requests processed | 40 / 40 |
| Pipeline crashes | 0 |
| Total estimated cost | ~$0.011 |
| Mean latency | ~3.3 s / request |
| Total wall time (sum of per-request latency) | ~130 s |

### Actions

| Action | Count |
| --- | ---: |
| `auto_resolve` | 15 |
| `route` | 13 |
| `escalate` | 10 |
| `reject` | 2 |

### Intents

| Intent | Count |
| --- | ---: |
| `access_request` | 9 |
| `data_pull` | 8 |
| `policy_question` | 8 |
| `bug_report` | 7 |
| `purchase_approval` | 6 |
| `out_of_scope` | 2 |

### Flags of interest

| Flag | Count | Notes |
| --- | ---: | --- |
| `prompt_injection` | 2 | REQ-036, REQ-037 |
| `prompt_injection_blocked` | 2 | Grant refused even though mock approval was `all` |
| `contains_pii` | 2 | REQ-038, REQ-039 (masked in audit output) |

## Safety / groundedness spot-checks

- **Tier 1 grants** (e.g. REQ-001, REQ-004, REQ-005): `grant_access` without `approved_by`; final action `auto_resolve`.
- **Tier 2/3 after mock approve** (REQ-002, REQ-003, REQ-006): gate ran (`approved_by=MOCK_APPROVER`); on success final action is now `auto_resolve` (not left as `escalate`).
- **Stub flakiness:** REQ-003 showed one failed `grant_access` (`upstream_5xx`) then a successful retry — both attempts logged.
- **Adversarial access:** REQ-036 / REQ-037 escalated; `grant_access` recorded with `error=prompt_injection_blocked` (no real grant).
- **Out of scope:** REQ-034 / REQ-035 → `reject`.
- **Uncovered policy:** REQ-040 → `escalate` with an explicit “docs do not cover…” answer and empty `citations` (expected).
- **PII:** SSN / email / phone / address paths flagged `contains_pii` and redacted in the audit record.

## Approval mode

Batch run used `TRIAGE_MOCK_APPROVE=all` so Tier 2/3 grants could exercise the post-approval path. Default without that env var is **deny** (gate still runs; grants are not executed).

## Known weaknesses

- Intent / routing / groundedness scores live in [eval_report.md](eval_report.md), not here.
- Mock “approve all” is not a real human; production must keep the gate interactive.
- One uncovered policy question (REQ-040) correctly escalates but still stores a short answer text without citations — by design for uncovered docs.
