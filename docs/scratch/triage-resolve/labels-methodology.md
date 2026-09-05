# Labels methodology (ticket 05)

Ground-truth `intent` + `action` for every `label_status: labeled` row in `requests.jsonl` (REQ-001–REQ-030). File: `evals/labels.json`.

## How the key was made

1. Read each labeled request text.
2. Map intent from the message purpose (access / data / policy Q / bug / purchase).
3. Choose action from `knowledge/` only:
   - **Access:** Tier 1 → `auto_resolve`; Tier 2/3 → `escalate` (`access_tiers.md`).
   - **Data:** aggregate → `route`; PII/regulated → `escalate` (`data_request_rules.md`).
   - **Policy:** answerable from docs → `auto_resolve` (e.g. call-recording archive = Tier 3).
   - **Bug:** → `route`.
   - **Purchase:** annualize spend, then bands in `purchase_limits.md` (`< $500` auto, `$500–$5k` route, `>$5k` escalate).
4. Cross-checked against classify/`decide` only as a sanity check; **authority is `knowledge/`**. Did **not** treat `results.jsonl` as truth where it auto-resolved Tier 2/3 grants (REQ-002/003/006).

Unlabeled REQ-031–040 are intentionally omitted (ticket 06 can score refusal separately).
