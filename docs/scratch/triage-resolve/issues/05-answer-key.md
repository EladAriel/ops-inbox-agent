# 05 — Write the answer key for labeled requests

**What to build:** A file that lists, for each labeled request, the correct intent and the correct action. Later scoring compares the program to this file. You make this key by reading the requests and the policy docs (the pack does not give answers). You may use classify runs from ticket 01 to help you check your thinking, but the key is your judgment against `knowledge/`.

**Blocked by:** None — can start anytime before eval (ticket 06). Doing it after you have seen classify output from 01 is fine.

**Status:** done

**Edit:** `evals/labels.json` (REQ-001–030). Ticket 06 loads this from `starter/run_evals.py` (`score_intent_accuracy`, `score_routing_correctness`). Methodology: `docs/scratch/triage-resolve/labels-methodology.md`. Tests: `tests/test_labels.py`.

## Notes

- **AI:** Use the OpenAI SDK for the model call (OpenRouter via `starter/config.py`).
- **Tests:** Use pytest for the step 4–5 checks (one easy message, then a handful including a tricky / adversarial one).
- **KISS:** Keep the smallest working design — no extra frameworks or layers beyond what this step needs.

## Acceptance criteria

- [x] Every labeled request id from `requests.jsonl` has an entry
- [x] Each entry has expected `intent` and expected `action`
- [x] Choices match the rules in `knowledge/` (access tiers, data rules, purchase limits, PII)
- [x] How the key was made is written down briefly (for the eval write-up later)
