---
name: debug-magic-oculus-import
description: Diagnose, reproduce, fix, and safely retry failed MetaGatherer tournament imports into Magic Oculus. Use for Oculus collection/API errors, roster or player-count mismatches, missing decks or standings, duplicate users, failed or ambiguous import journal rows, and requests to identify a missing player, add regression tests, prepare a PR, or re-upload one tournament.
---

# Debug Magic Oculus Import

Diagnose one tournament end to end without exposing secrets or accidentally creating a duplicate Oculus event. Separate data repair, code repair, and the external retry into explicit stages.

## Core workflow

1. Read the GitHub issue and its newest comments. Extract the MetaGatherer tournament ID, title, date, counts, exception type, and exact error.
2. Inspect the current PR/branch state. Start a fresh branch from current `main`, or update the existing open issue branch only after verifying its PR is `OPEN`.
3. Inspect production read-only. Run code on the server so it reads its own environment; never print or copy `.env`, `DATABASE_URL`, tokens, or API credentials.
4. Run `scripts/inspect_tournament.py TOURNEY_ID --fetch-aetherhub` in the deployed repo when available. Otherwise use an equivalent read-only Python snippet with `SessionLocal`.
5. Compare three sets independently:
   - MetaGatherer participants with names, decks, and `final_place`;
   - AetherHub `players` roster;
   - AetherHub final `standings`.
6. Inspect the `magicoculus_imports` journal and, when a POST may have reached Oculus, query Oculus before attempting any retry.
7. State the root cause and name every missing/extra player. Do not reduce a mismatch to counts only.
8. Add the smallest unit test reproducing the raw shape of the failure, then implement the code fix. Run focused tests and the full suite.
9. Repair production data only with evidence. Never guess a missing deck from player history; request confirmation when the current tournament has no authoritative deck value.
10. Run `python3 cli.py magicoculus preview TOURNEY_ID` before any POST. Review date, club, URL, player count, positional places, names, and decks.
11. Retry with `python3 cli.py magicoculus send TOURNEY_ID --execute` only after confirming no Oculus tournament was created and the local journal permits a retry. Record and report the resulting Oculus tournament ID and URL.
12. Open or update the PR. Never merge it.

## Safety gates

- Treat `send --execute`, journal deletion/reset, participant edits, and production DB changes as external mutations. Resolve the exact tournament and rows read-only first.
- A timeout or HTTP error does not prove the POST failed. Check the journal and Oculus existing tournaments before clearing any guard.
- Never bypass `MagicOculusImporter.import_once()` for convenience; its durable `pending` row prevents duplicate POSTs.
- Never send Telegram debug messages or broadcast notifications. Prefer CLI/server-side diagnostics.
- Never infer a missing deck from a previous tournament. Historical decks are leads, not proof.
- Do not alter final places to make positional validation pass. Reconcile them with authoritative AetherHub standings.
- Preserve unrelated production records and worktree changes.

## Diagnose by failure class

- `MagicOculusCollectionError`: inspect tournament metadata, participant names/decks/places, AetherHub roster, and standings before looking at HTTP.
- Roster count/set mismatch: compute `players - bot`, `standings - bot`, and `bot - standings`; normalize case, `ё/е`, whitespace, and both two-word name orders.
- Missing deck: locate the participant and current-tournament evidence. Stop before upload if the deck is unknown.
- Duplicate name/user: inspect real Telegram users and negative-`tg_id` placeholders plus their participant/deck history. Merge only when identity is unambiguous and use project service methods.
- Positional places error: require exactly `1..N` after AetherHub filtering; find the first missing or duplicated place.
- `MagicOculusApiError`: inspect resolved city/club/format references, HTTP status/body summary, and the journal. Do not retry 5xx/timeouts blindly.
- Journal says `pending` or `error`: check Oculus by date, club, format, and AetherHub URL before any journal repair.

## Required references

Read [references/data-sources.md](references/data-sources.md) before querying production or deciding which source is authoritative.

Read [references/code-map.md](references/code-map.md) before changing implementation or choosing tests.

## Expected handoff

Report:

- exact tournament and AetherHub URL;
- bot/players/standings counts;
- missing and extra names;
- root cause;
- production data changed, if any;
- focused and full test results;
- PR link;
- Oculus retry result or the precise missing fact blocking it.
