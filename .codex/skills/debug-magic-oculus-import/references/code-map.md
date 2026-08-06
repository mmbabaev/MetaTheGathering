# Code and test map

## Runtime path

```text
bot/scheduler.py
  maybe_announce_meta_gather_completed()
  import_closed_tournament_to_magicoculus()
    ↓
services/magicoculus.py
  MagicOculusTournamentCollector.collect(validate_aetherhub=True)
  MagicOculusClient
  MagicOculusImporter.import_once()
    ↓
core/models.py
  MagicOculusImport journal
```

## Key files

- `services/magicoculus.py`: payload models, collection/validation, Oculus API client, reference resolution, positional export, and one-shot journal guard.
- `services/aetherhub_service.py`: fetches/parses `players`, `standings`, rounds, and scores.
- `services/aetherhub_import_service.py`: matches/creates users, registers participants, applies places, and stores pairings.
- `services/user.py`: flexible name matching and safe placeholder merge rules.
- `services/names.py`: participant display-name formatting.
- `bot/scheduler.py`: automatic trigger after completion, worker/session boundary, feature flag, and owner-only error DM.
- `cli/magicoculus.py`: supported `preview` and explicit `send --execute` operations.
- `core/models.py`: `Tournament`, `Participant`, `User`, `Archetype`, `RoundPairing`, and `MagicOculusImport`.
- `core/config.py`: non-secret Oculus base URL setting; secrets/database config must never be printed.
- `docs/scheduler.md`: operational behavior and retry policy.

## Tests by responsibility

- `tests/test_magicoculus_collector.py`: missing metadata/decks, duplicate names, AetherHub validation, player filtering, and place completeness.
- `tests/test_magicoculus_client.py`: reference lookup, request payload, API errors, and result parsing.
- `tests/test_magicoculus_importer.py`: durable journal, success/error state, and duplicate-send prevention.
- `tests/test_magicoculus_journal.py`: journal constraints and lookup behavior.
- `tests/test_cli_magicoculus.py`: preview/send command boundaries.
- `tests/test_aetherhub_service.py`: parser and participant-import regressions, including roster/standings discrepancies.
- `tests/test_merge_placeholder.py` and `tests/test_tournament_service.py`: placeholder identity merging and participant collisions.
- `tests/test_meta_gather_completed.py`: automatic Oculus trigger, feature flag, worker boundary, and owner error notification.
- `tests/test_tournament_migration.py`: historical bulk migration only; do not use it for a single current tournament unless the bug is in that path.

## Test design

Reproduce raw upstream shape, not just the final exception. For roster mismatch cases, construct `AetherhubTournamentData` with independently controlled `players`, `standings`, and `rounds`. Assert:

- exact missing player is registered or excluded according to the product rule;
- reversed two-word name order does not duplicate a participant;
- missing current-event deck still blocks export;
- places remain contiguous for positional Oculus import;
- retry protection remains intact.

Run the smallest relevant files first, then `python3 -m pytest tests/ -q`.
