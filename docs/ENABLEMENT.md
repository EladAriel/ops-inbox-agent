# Enablement note — how to extend this system

Short guide for another product team. Plain steps only.

## Add a new intent (a new kind of request)

1. Add the new name to the `Intent` list in `starter/state.py`.
2. Teach the model the new name in `starter/prompts.py` (classify prompt). Give 1–2 short examples of what counts and what does not.
3. List which fields to pull out for that intent in `_FIELDS_BY_INTENT` in `starter/pipeline.py`.
4. Write a small decide function in `starter/decide.py` that sets `action` (and `route_to` if needed). Register it in `INTENT_HANDLERS`.
5. If the rules live in a policy file, add a short markdown file under `knowledge/` and cite it from decide.
6. Add a few sample lines to `requests.jsonl`, labels in `evals/labels.json`, and a pytest that checks the decide path.
7. Run: `python3 -m starter.pipeline` and `python3 -m starter.run_evals`.

## Add a new tool (a new action the pipeline can call)

1. Add a plain function in `tools/stub_tools.py` (same style as `lookup_user` / `grant_access` / `create_ticket`). Log every call.
2. Call it from `execute_tools` in `starter/pipeline.py` (or from a helper in `starter/tool_actions.py`).
3. If the tool **changes** something important (like granting access), stop for human approval first — same pattern as `human_approval_gate` before `grant_access`.
4. Record each call on `state.tool_calls`. On failure: retry once if it is flaky, then escalate.
5. Add a test that the tool runs when you expect, and does **not** run when approval is denied.

## Add a new eval case (a new test message with a known answer)

1. Add the message to `requests.jsonl` with a new `id` (for example `REQ-041`).
2. If it should count in intent/routing scores, add a row to `evals/labels.json` with the correct `intent` and `action`. Take those answers from `knowledge/`, not from an old `results.jsonl`.
3. If it is only for refusal or tool checks, you can leave it unlabeled and still assert behavior in a pytest or in the refusal cohort logic in `starter/run_evals.py`.
4. Run `python3 -m starter.run_evals` and confirm the metric you care about moved the way you expect.
