# AI-use & time statement

## Time

About **~5 hours** wall-clock across tickets 01–07 (approximate; within the assignment hard stop).

## Tools (two different roles)

| Role | What |
| --- | --- |
| **Coding assistants** | Cursor (Composer / agent) — scaffolding stages, pytest, eval harness, and drafts of these write-ups |
| **Pipeline / eval models** | OpenRouter via `starter/config.py`: `openai/gpt-4o-mini` for classify / extract / ground; `openai/gpt-4o` as the eval groundedness judge (`JUDGE_MODEL`) |

Coding-assistant use is separate from the runtime pipeline model. No extra LLM stage was added for this hand-in ticket.

## Where AI materially contributed

- Pipeline stage seams (classify → extract → decide → ground → tools/gate → audit)
- Pytest coverage around decide, gate, PII, and eval scorers
- First drafts of run/eval reports and this design note (edited by hand for accuracy)

## One accepted suggestion

**Drop hybrid/RRF retrieval → simple embedding top-k** in `starter/knowledge_index.py`. Enough for short `knowledge/` docs, easier to audit, fewer moving parts.

## One rejected / corrected suggestion

1. **Rejected:** keep a `TRIAGE_MOCK_LLM` classify mock for “free” batch runs — removed in favor of real OpenRouter calls; only the **approval** mock (`TRIAGE_MOCK_APPROVE`) stayed for gated grants offline.
2. **Corrected:** Tier 2/3 gold labels taken from `knowledge/` (expect escalate / gate), **not** copied from an early `results.jsonl` that had post-approve `auto_resolve` — so the answer key tracks policy, not a temporary pipeline quirk.
