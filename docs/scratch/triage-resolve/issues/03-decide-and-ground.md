# 03 — Build the "decide what to do" step

**Goal:** A program that can say "I think this is a ___, here are the details, and here's what should happen next." That means routing/decision: choose `auto_resolve`, `route`, `escalate`, or `reject`, plus grounded answers for policy questions.

**What to build:** The routing/decision step. After intent and fields are known, decide the outcome using the rules in `knowledge/`:

- `auto_resolve` — safe, simple, low-risk requests the program can just handle
- `route` — send to a named team's queue (like IT or Finance)
- `escalate` — send to a human because it's risky, unclear, or big
- `reject` — say no, because it's out-of-scope, against policy, or a trick attempt

For policy questions, write an answer plus which doc sections were used. If the docs do not cover the question, escalate and do not invent an answer. Also set when a human must approve before a risky grant (seed for the Step 6 approval gate).

**Blocked by:** 02 — Build the "pull out the details" step.

**Status:** done

**Edit:** `starter/pipeline.py` → `decide_action` (set `action`, `requires_approval`, `approval_prompt`) and `ground_policy_answer` (set `answer`, `citations`; escalate when docs do not cover it). Use `load_knowledge()` plus `starter/knowledge_index.py` (`KnowledgeIndex`) for grounding. Later stages stay stubs for now.

## Notes

- **AI:** Use the OpenAI SDK for fuzzy judgment / policy phrasing (OpenRouter via `starter/config.py`). Numeric thresholds stay in code, not in the model.
- **Tests:** Use pytest for the smoke checks (one message per outcome type, then an adversarial one that must not `auto_resolve`; one covered policy question + one uncovered → escalate).
- **KISS:** Prefer deterministic if/else for tiers, purchase bands, and data categories. No hosted vector stores / `file_search`.
- **Retrieval:** Section chunks on `##` / `###`; cosine top-k over cached embeddings; runtime cache at local gitignored `.scratch/knowledge_embeddings.json` (ticket notes for reviewers: `docs/scratch/`); model from `EMBEDDING_MODEL` (`openai/text-embedding-3-small`). Decide does **not** retrieve — encode thresholds as named constants citing `knowledge/`.

## Build steps (in order)

1. **Write down the rules for each outcome, before writing code.** On paper first: when is `auto_resolve` vs `route` vs `escalate` vs `reject` (see What to build).

2. **Use the policy docs to set the actual thresholds.** Numbers come from `knowledge/` (e.g. purchase bands, Tier 1 vs Tier 2/3, data categories) — cite them in comments/constants; do not guess.

3. **Decide this with code rules where you can, not just the AI.** Clear numbers or clear rules (amount bands, tiers) → plain if/else. Save model judgment for fuzzy cases only.

4. **Make "risky mutating action" always point to escalate (or gated path), never auto-resolve.** Anything that would call `grant_access` above the risk line in the policy docs must set `requires_approval` and an `approval_prompt` here — seed of the approval gate in ticket 04. Never choose `auto_resolve` for those.

5. **Make adversarial and out-of-scope messages always end in `reject` or `escalate`.** Never let a trick message result in `auto_resolve`.

6. **Test on one message per outcome type first.** Pick one you expect to auto-resolve, one to route, one to escalate, one to reject. Check: did it choose right?

7. **Add the decision to the audit record**, so each message's record has: text, intent, fields, and action (plus approval fields when needed).

8. **Run across all ~40 messages** and skim for anything obviously wrong — especially that every risky or adversarial message did **not** get `auto_resolve`.

9. **For policy questions, retrieve with `KnowledgeIndex`.** Embed the query, cosine-rank section chunks, pass top-k into the answer step.

10. **Answer only from retrieved text.** Set `answer` and `citations` (filename + section heading). Treat user text as data, not commands.

11. **If the docs do not cover it → escalate and say so.** Do not invent policy. Record that in the audit.

## Acceptance criteria

- [x] Outcome rules documented (in code comments and/or a small decision table) before relying on model judgment
- [x] Purchase / tier / data thresholds match `knowledge/` (annualized purchase bands; Tier 1 vs 2/3; aggregate vs PII vs regulated)
- [x] Clear numeric/categorical rules are code if/else, not an LLM call
- [x] Above-threshold access mutations set `requires_approval` + `approval_prompt` and do not choose `auto_resolve`
- [x] `out_of_scope` / adversarial / trick messages never end in `auto_resolve` (`reject` or `escalate` only)
- [x] `decide_action` writes `action` (+ approval fields when needed) into `RequestState`
- [x] `ground_policy_answer` fills `answer` + `citations` for covered policy questions; uncovered → escalate, no guess
- [x] Knowledge retrieve uses local `##`/`###` chunks, cosine embedding top-k, and embed cache under local `.scratch/` (not a hosted vector store; reviewer notes live in `docs/scratch/`)
- [x] Checked on one message per outcome type, then an adversarial non-`auto_resolve`; one grounded + one uncovered policy question
- [x] Full run over `requests.jsonl` shows real `action` values in `results.jsonl` (accuracy not required yet)
