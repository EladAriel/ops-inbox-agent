# Work audit summary

Condensed timeline of what we built for Triage & Resolve. Ticket notes for reviewers: [`docs/scratch/`](scratch/). Not a day-by-day log — the **general steps** in order.

## 0. Process setup

- Encoded README hard constraints in a Cursor rule; ticket/issue notes for hand-in live under `docs/scratch/`.
- Local `git init` for this take-home (separate from parent folder git).

## 1. Classify intent (ticket 01)

- Structured LLM classify (`IntentClassification`) + untrusted-input prompt + pytest seams.
- Tried a keyword LLM mock, then removed it.
- Wired OpenRouter via `starter/config.py` / pydantic-settings / `.env` (secrets out of git).
- Fixed Provisioning-key 401; smoke progressed 1 → 5 → full 40 requests → `results.jsonl`.

## 2. Extract fields (ticket 02)

- Structured extract + per-intent field filter; optional `lookup_user`; purchase amounts annualized when monthly.
- Live smoke + full corpus run.

## 3. Decide + ground (ticket 03)

- Hardened embedding `KnowledgeIndex` (runtime embed cache stays local/gitignored; ticket notes in `docs/scratch/`); dropped hybrid/RRF for simple top-k.
- Deterministic `decide_action` from `knowledge/` (thresholds, tiers, routes, OOS reject, injection never auto).
- `ground_policy_answer` with citations; uncovered / empty retrieve → escalate.
- Moved maps to `starter/decide.py`; extract emits `access_tier` / `data_category`.
- Fixed OOS classify (payroll/PTO), grounding retrieve query, and empty-hits short-circuit.
- Full 40-request smoke before tools.

## 4. Tools, approval gate, PII (ticket 04)

- Tier ≥2 `human_approval_gate` before `grant_access` (default deny; `TRIAGE_MOCK_APPROVE` for batch).
- `try_grant_access`: one retry + backoff, then escalate; routes via `create_ticket` with safe payload.
- PII mask (`starter/pii.py`); helpers in `starter/tool_actions.py`.
- Expanded adversarial markers / `finalize_decide`.
- Audit/usage modules: tokens, cost, latency, per-request isolation, nested PII redaction.
- Restored full `requests.jsonl`; full batch run (~$0.011, ~3.3 s mean) + `reports/run_report.md`.

## 5. Answer key (ticket 05)

- `evals/labels.json` for REQ-001–030 from `knowledge/` (not from buggy Tier 2/3 `auto_resolve` in early results).
- Label schema tests + methodology note in `docs/scratch/triage-resolve/`.

## 6. Eval harness (ticket 06)

- Per-dimension scorers in `starter/run_evals.py` (intent, routing, groundedness judge, refusal, tool validity, cost/latency).
- Separate `JUDGE_MODEL`; error isolation for crashed requests / scorers.
- Live metrics → `reports/eval_report.md` (intent 1.0, routing 0.9, groundedness ~0.86, refusal 1.0, tool ~0.91).

## 7. Hand-in docs (ticket 07)

- `docs/DESIGN.md`, `docs/AI_USE.md`, README Submission (how to run), reports linked.
- Write-ups later moved under `docs/`.

## Still open (called out in audit, not blocking 07)

1. Align Tier 2/3 final `action` vs labels (`escalate` vs post-approve `auto_resolve`) without removing the gate.
2. Block `grant_access` when `lookup_user` is missing.
3. Optionally print eval cost with more than 3 decimal places.
4. Commit remaining dirty pipeline/eval tree as needed.
