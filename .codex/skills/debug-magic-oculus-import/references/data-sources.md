# Data sources and authority

## Source priority

| Question | Primary source | Secondary source |
|---|---|---|
| Which event failed? | GitHub issue/error DM: MetaGatherer tournament ID | `tournaments` row |
| Who actually played? | Final AetherHub `standings` | AetherHub `players` and round pairings |
| Which deck was registered? | Current tournament `participants.archetype_id` | Explicit organizer/player confirmation |
| What was the final place? | Final AetherHub `standings` | `participants.final_place` after import |
| Was Oculus POST attempted? | `magicoculus_imports` journal | Server logs |
| Was an Oculus event created? | Oculus tournaments/detail API | Imported journal ID when status is `imported` |

Never use a previous tournament's deck as authoritative for the current event.

## GitHub

Read the issue body and newest comments with `gh issue view`. Errors commonly contain:

- tournament title and MetaGatherer ID;
- collection/API exception class;
- MetaGatherer deck count and AetherHub player count.

Check related PR state before pushing. Never append commits to a merged or closed PR branch.

## Production database

Relevant tables/models:

- `tournaments`: ID, title, club, status, dates, `aetherhub_url`, completion timestamp;
- `participants`: tournament/user/deck relation and `final_place`;
- `users`: real Telegram users have positive `tg_id`; AetherHub placeholders use negative IDs;
- `archetypes`: exported deck names;
- `round_pairings`: imported rounds, opponents, tables, and match scores;
- `magicoculus_imports`: durable one-shot journal with `pending`, `error`, or `imported`, Oculus ID, warnings, and error summary.

Run diagnostics on the server inside the deployed repository. Let `core.database.SessionLocal` read configuration internally. Output only tournament facts; do not output environment values, tokens, headers, cookies, or connection strings.

The bundled `scripts/inspect_tournament.py` is read-only. With `--fetch-aetherhub` it performs public AetherHub requests but no Oculus POST.

## AetherHub

`AetherhubService.fetch_tournament(url)` returns:

- `players`: registration roster derived primarily from early/round-one data;
- `standings`: ordered final places when published;
- `rounds`: directed pairings and optional match scores.

Do not assume `players` and `standings` have equal counts. A player can appear only in standings. Compare normalized identities, not raw strings, because pages can reverse `Имя Фамилия` and `Фамилия Имя`.

For a finished event, standings are authoritative for participation and place. `players` remains useful to explain import history and early roster discrepancies.

## Magic Oculus

The public base URL comes from `settings.MAGIC_OCULUS_API_URL`. Use `MagicOculusClient` rather than hand-built requests.

Before retrying an ambiguous failure:

1. inspect `magicoculus_imports`;
2. query existing Oculus dailies by date/club/format;
3. inspect a candidate tournament detail and AetherHub URL;
4. repair the exact journal row only after proving no event was created.

`cli.py magicoculus preview ID` is read-only. `cli.py magicoculus send ID --execute` performs the real POST and must be the last step.

## Logs

Filter server logs by the exact tournament ID, exception class, or `MagicOculus` marker. Logs are supporting evidence, not the source of player/deck truth. Do not print broad log ranges that may contain unrelated user data.
