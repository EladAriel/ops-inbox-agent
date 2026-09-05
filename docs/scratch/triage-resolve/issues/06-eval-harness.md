# 06 — Build the score report

**Goal:** A program that grades the pipeline with numbers, not vibes. That means an eval harness: one command scores `results.jsonl` / a live run across several categories, not one combined score.

**What to build:** Fill `starter/run_evals.py` so it measures each of these (from the README):

- intent classification accuracy (on the ~30 labeled messages)
- action/routing correctness
- groundedness/faithfulness of policy answers (did the citation actually support the answer?)
- refusal rate on adversarial + out-of-scope messages
- tool-call validity (including how it handled the ~15% random failures)
- cost (tokens) and latency per request

At least one score is plain code (programmatic). At least one score uses an LLM judge for groundedness, with a short note on how that judge can be wrong.

**Blocked by:** 04 — Call tools only when allowed; hide private personal data; 05 — Write the answer key for labeled requests.

**Status:** done

**Edit:** `starter/run_evals.py` → fill every scorer TODO: `score_intent_accuracy`, `score_routing_correctness`, `score_groundedness` (LLM judge), `score_refusal_rate`, `score_tool_call_validity`, `score_cost`, `score_latency` (latency already has a stub mean). Load the answer key from ticket 05 (`evals/labels.json`). Keep `print_metrics_table` / `run` / `main` unless you need a small hook for the judge model (`--judge-model` already exists).

## Notes

- **AI:** Use the OpenAI SDK for the LLM-as-judge call (OpenRouter via `starter/config.py`). Programmatic scorers stay plain code.
- **Tests:** Use pytest for the programmatic checks (intent/routing vs labels, refusal on adversarial/OOS, approval gating / tool failure logging).
- **KISS:** Fill the existing scorer stubs; no extra eval framework. One command: `python3 -m starter.run_evals`.

## Build steps (in order)

1. **List out the categories you need to measure**, straight from the README (see What to build). Keep them as separate rows — do not collapse into one aggregate score.

2. **Split your checks into two kinds: programmatic and AI-judged.** The README requires at least one of each.
   - **Programmatic:** exact comparisons (predicted intent vs label; risky actions went through approval; adversarial/OOS never `auto_resolve`).
   - **LLM-as-judge:** fuzzier checks — e.g. whether a policy answer is faithful to the cited document text.

3. **Build the programmatic checks first**, since they are simpler and more reliable:
   - Compare intent labels for the ~30 labeled messages; calculate percent correct.
   - Check that every message needing approval actually went through the approval gate.
   - Check that every adversarial/out-of-scope message ended in `reject` or `escalate`, never `auto_resolve`.
   - Check that tool call failures were logged, and how the program behaved (retried? escalated?).
   - Sum up total tokens and average latency per message (wire `score_cost` / `score_latency`).

4. **Build the LLM-judge check next.** Feed the judge: the policy question, the cited document text, and the program's answer. Ask: "Is this answer fully supported by the cited text? yes/no, and why." Run this for each policy-question message (`score_groundedness`).

5. **Write down the judge's limitations honestly.** The README asks for this. Examples: too lenient, same blind spots as the main model if it is the same model, inconsistent across runs. A sentence or two is enough — code comment or hand-in docs.

6. **Print a metrics table, not one combined score.** Show each category (accuracy, routing correctness, groundedness, refusal rate, tool validity, cost, latency) as its own row via `print_metrics_table`.

7. **Run the whole eval harness with one command** (`python3 -m starter.run_evals` or equivalent) and check that it runs cleanly against your pipeline output / `results.jsonl`.

8. **Look at the weak spots and decide if you have time to go fix them.** If accuracy is bad in one category, this is the last chance to patch earlier steps (02–07) before the write-up.

## Acceptance criteria

- [x] `python3 -m starter.run_evals` prints all required metrics (not one combined score)
- [x] Intent and routing scores use the answer key from ticket 05 (`evals/labels.json`) (programmatic)
- [x] Groundedness uses an LLM-as-judge check on policy-question answers
- [x] Refusal, tool-call validity, cost, and latency are implemented
- [x] Adversarial/OOS items never scored as successful `auto_resolve` for refusal
- [x] Tool failures / approval gating are reflected in tool-call validity
- [x] Judge limits / biases are written down (code comment or hand-in docs)
- [x] Pytest covers at least the programmatic scoring smoke paths
