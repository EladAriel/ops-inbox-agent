# 04 — Build the safety gate for risky actions

**Goal:** A program with a real safety brake: nothing risky happens without a human pressing the button. That means tool execution with an approval gate for mutating grants, plus PII masking in the audit trail.

**What to build:** Call tools only when allowed, and hide private personal data:

- `route` → `create_ticket` (no raw PII in the payload)
- Tier 1 `auto_resolve` access → `grant_access` without a human gate
- Tier 2/3 (and any `requires_approval` seeded in ticket 03) → pending approval; `grant_access` only after `human_approval_gate` returns true (in batch runs, a mock yes/no is fine, but the stop must be real)
- If `grant_access` fails (~15% stub flakiness), retry with short backoff then escalate; record every try
- `redact_pii` masks SSN / email / phone / address per `knowledge/pii_handling.md` and flags PII when present
- Running the pipeline writes a full `results.jsonl`

**Blocked by:** 03 — Choose the action and answer policy questions from the docs.

**Status:** done

**Edit:** `starter/pipeline.py` → `human_approval_gate`, `execute_tools`, `redact_pii`. Wire order stays in `process_request` (approve before grant). Call `grant_access` / `create_ticket` from `tools`; append to `state.tool_calls`. Ticket 03 already seeds `requires_approval` + `approval_prompt` for Tier 2/3 in `starter/decide.py`. Do not edit the stub tools themselves.

## Notes

- **AI:** Gate / tools / redact are deterministic (or a mock approver). No new LLM stage required; earlier stages keep using the OpenAI SDK via `starter/config.py`.
- **Tests:** Use pytest for the approve → grant path, the deny / no-approval → never grant path, and Tier 1 still granting without a gate; optionally assert failure/retry attempts land in `tool_calls`.
- **KISS:** Mock yes/no for batch/eval is fine; the control-flow stop must be real. Prefer retry-then-escalate for ~15% stub failures. No editing `tools/stub_tools.py`.

## Build steps (in order)

1. **Find every spot where a mutating tool gets called.** In this project that is `grant_access`. Mutating means it changes something real — not just looking something up or making a ticket.

2. **Check the risk level against the policy docs.** Use `knowledge/access_tiers.md`: Tier 1 is below the line (may auto-grant); Tier 2/3 are above it and must never run automatically.

3. **Build a pending-approval path instead of calling the tool right away.** When `requires_approval` is set, do not call `grant_access` immediately. Hold it as waiting for a human confirm.

4. **Build the confirm step.** Implement `human_approval_gate` so it only returns true after an explicit approved-by-human signal (mock decision map / env / test fixture for batch is fine). Proof matters: nothing risky runs without that yes.

5. **Log the whole thing.** Record what action was requested, why it is risky, whether it was approved or denied, and by whom (even if `"MOCK_APPROVER"`). Put this on the audit record / `tool_calls` (`ToolCall.approved_by`).

6. **Test the happy path.** Simulate a human approving, and check that `grant_access` runs only after that approval — never before.

7. **Test the refusal path.** Simulate a human saying no (or nobody approving), and check that `grant_access` never runs.

8. **Test that low-risk actions still work without approval.** Tier 1 `auto_resolve` access should still call `grant_access` with no gate.

9. **Cross-check against ticket 03.** Every message that set `requires_approval` for a mutating risky grant must flow through this gate — no exceptions.

10. **Wire `route` and failure handling.** `route` calls `create_ticket` with no raw PII. On `grant_access` failure, retry with short backoff then escalate; every attempt goes in `tool_calls`.

11. **Mask PII in the audit output.** Implement `redact_pii` (SSN last-4, mask email/phone/address) and flag PII presence in `state.flags` per `knowledge/pii_handling.md`.

12. **Run across all ~40 messages** and skim `results.jsonl` for tool calls, approval outcomes, and redacted fields. Accuracy grading comes later in eval.

## Acceptance criteria

- [x] Mutating tool call sites identified; only `grant_access` is gated (tickets are not)
- [x] Risk threshold matches `knowledge/access_tiers.md` (Tier 1 auto; Tier 2/3 gated)
- [x] `human_approval_gate` is a real stop: `grant_access` does not run unless it returns true
- [x] Denied / no-approval path never calls `grant_access`
- [x] Tier 1 may auto-call `grant_access` without approval
- [x] Approval outcome (and approver) logged on the audit record / `tool_calls`
- [x] Every ticket-03 `requires_approval` path flows through the gate
- [x] `route` uses `create_ticket` with no raw PII in the payload
- [x] `grant_access` failures are handled (retry then escalate) and every try is in `tool_calls`
- [x] `redact_pii` masks sensitive data in the audit record and flags PII when present
- [x] Pytest covers approve / deny / Tier-1 no-gate paths
- [x] Full run over `requests.jsonl` writes tool/approval/PII-aware records to `results.jsonl`
