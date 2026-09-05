# 07 — Write the short papers for hand-in

**Goal:** Hand-in write-ups that defend the system: a short design note (mini-ADR), an honest AI-use & time statement, and a human-readable run report. Repo stays runnable with secrets out of git.

**What to build:** Design note (how it works, approval stop, errors, cost ideas, what you skipped), AI-use and time note, and a short human-readable run report. Repo stays runnable with secrets out of git.

**Blocked by:** 04 — Call tools only when allowed; hide private personal data. Practically also 06 — need cost/latency numbers from the eval run for the design note.

**Status:** done

**Edit:** New docs only — `docs/DESIGN.md` (or equivalent mini-ADR), AI-use in `docs/AI_USE.md` (linked from README), short run report (e.g. `reports/run_report.md` alongside `results.jsonl`). Ticket notes for reviewers: `docs/scratch/`. No starter `TODO` methods. Optionally touch `requirements.txt` if packages were added in earlier tickets.

## Notes

- **AI:** Coding assistants may help draft the write-ups — disclose that honestly. Keep coding-assistant use separate from the pipeline model (`starter/config.py` / OpenRouter). No new LLM stage for this ticket.
- **Tests:** No new pytest required — acceptance is the README deliverables checklist and human review of the write-ups.
- **KISS:** Design note ≤1–2 pages; AI-use statement short (a few honest sentences per point); no extra frameworks or packaging tooling.

## Build steps (in order)

1. **Draw the architecture diagram first, even rough.** Box-and-arrow is fine: message in → classify → extract → decide → (policy answer OR tool call) → approval gate if needed → audit record out. Hand-drawn is explicitly fine.

2. **Explain why this orchestration pattern.** Say plainly why a straight-line pipeline beats multi-agent chatter: simple, deterministic steps; multi-agent earns no bonus by itself (README hint).

3. **Point out where plain code beats AI judgment, and why.** Example: amount thresholds / Tier gates are hard rules from `knowledge/`, not LLM guesses — they must be exact and auditable every time.

4. **Explain error-handling and the approval-gate design.** How `grant_access` failures are handled (retry/backoff then escalate) and exactly how the human-approval gate stops Tier 2+/Restricted mutations before the tool runs.

5. **Give cost/latency numbers from the eval run (ticket 06 / Step 10),** then answer how you'd cut API cost ~50% in production without losing quality (e.g. cheaper model for easy classify, cache repeated policy Qs, batch small calls).

6. **List what you deliberately did not build, and why.** Graded content: "didn't build X because Y; with 2 more days I'd add Z."

7. **Keep the design note to 1–2 pages.** Prefer decisions over long explanation; bullets are fine.

8. **Write the AI-use & time statement.** Total time spent; AI tools used (coding assistants vs pipeline model); where AI materially contributed; one accepted suggestion + why; one rejected/corrected suggestion + why. Keep it short.

9. **Ensure a short human-readable run report exists** (e.g. `reports/run_report.md`) next to / alongside `results.jsonl`.

10. **Confirm secrets stay out of source control** and that run steps for the pipeline (and eval) are documented.

## Acceptance criteria

- [x] Design write-up (≤1–2 pages) includes architecture diagram, orchestration rationale, deterministic-vs-LLM callouts, approval gate + tool-failure handling, cost/latency + ~50% cost-cut idea, deliberate non-goals / 2-more-days
- [x] AI-use & time statement lists time spent, tools used (assistants vs pipeline model), material contributions, one accepted + one rejected/corrected suggestion
- [x] Short human-readable run report exists (e.g. under `reports/` alongside `results.jsonl`)
- [x] Secrets stay out of source control; how to run the pipeline is documented
- [x] Write-ups stay short (design ≤2 pages; AI-use a few honest sentences per point)
