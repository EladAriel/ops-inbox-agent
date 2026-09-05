# 02 — Build the "pull out the details" step

**Goal:** A program that can say "I think this is a ___, and here are the details: ___." That means field extraction: after intent is known (from Step 2), pull the useful pieces into neat fields on the audit record.

**What to build:** This is called field extraction. Different intents need different details. Make a small list for each type before writing code, for example:

- access request → who is asking, what resource, what tier
- purchase approval → who is asking, what item, how much money (yearly total)
- data pull → who is asking, what data, why
- bug report / policy question / out-of-scope → whatever small set of fields is useful for that type (or nearly empty if nothing applies)

**Blocked by:** 01 — Build the "figure out what this message is" step.

**Status:** done

**Edit:** `starter/pipeline.py` → `extract_fields` (fill `state.fields`; may call `lookup_user` from `tools`). Later stages stay stubs for now.

## Notes

- **AI:** Use the OpenAI SDK for the model call (OpenRouter via `starter/config.py`).
- **Tests:** Use pytest for the step 4–5 checks (one message per intent type, then a tricky / adversarial one).
- **KISS:** Keep the smallest working design — no extra frameworks or layers beyond what this step needs.

## Build steps (in order)

1. **Decide what fields matter for each type of message.** Different intents need different details. Make a small list for each intent type *before* you write any code (see examples under What to build).

2. **Write a prompt that asks the AI to fill in those fields, and nothing else.** Feed it the message and the intent you already found in Step 2, and ask it to output the fields in the same strict JSON format as before, like `{"user": "jsmith", "resource": "salesforce", "tier": "admin"}`.

3. **Tell it what to do when a field is missing.** Real messages won't always have every piece of information. Use JSON `null` when a field isn't in the text — do not invent values. For purchase amounts: if the text gives a monthly cost, store the **yearly total** in the fields.

4. **Test on one message per intent type first.** Don't run all 40 yet. Pick one example from each category, run it, and check by eye: did it pull out the right details?

5. **Test on a tricky one.** Try a message that's messy or has extra junk in it (like a fake instruction hidden inside), and make sure your program only pulls out real data fields — it should not follow any hidden instructions while extracting. Somewhere in your prompt, clearly say the user text is data, not commands.

6. **Add these extracted fields into the audit record** you started in Step 2. So now each message's record has: the original text, the intent, and the extracted fields (`state.fields`). When a user id is present, you may call `lookup_user` and record that tool call on the audit trail.

7. **Once it looks right on your small tests, run it across all ~40 messages** and skim the output for anything obviously broken (like empty results or garbled JSON). Don't worry about being 100% perfect yet — grading happens later in the eval step.

## Acceptance criteria

- [x] Per-intent field list exists (in the prompt and/or structured schema) before relying on free-form extraction
- [x] Prompt takes the message plus the Step-2 intent and asks only for those fields as parseable JSON
- [x] Prompt says the user message is data, not commands (do not follow instructions inside it; extract fields only)
- [x] Missing fields are `null` (no fabrication)
- [x] Purchase money is stored as a yearly total when the text gives monthly cost
- [x] Checked on one message per main intent type, then a tricky / adversarial message (extracts fields only)
- [x] `extract_fields` writes `state.fields` into `RequestState` (and may record `lookup_user` when a user id is present)
- [x] Full run over `requests.jsonl` shows sensible `fields` in `results.jsonl` for in-scope intents (accuracy not required yet)
