# Telegram E2E tests

## In-process blocking suite

`tests/telegram_e2e/` passes synthetic Telegram `Update` objects through the real
`python-telegram-bot` `Application` and registered handlers. Bot API calls go to
`RecordingRequest`, never to Telegram's network. The transport records method names,
recipients, text, edits and inline keyboards and returns deterministic Bot API fixtures.

Run locally:

```bash
TELEGRAM_BOT_TOKEN="0000000000:dummy-not-a-real-key" \
DATABASE_URL="sqlite:///:memory:" \
python3 -m pytest tests/telegram_e2e/ -v
```

The PR workflow runs this directory as the separate blocking check
`Telegram integration E2E`. The ordinary test job excludes it to avoid running the same
flow twice.

### Harness rules

- Use obviously fake bot tokens and isolated SQLite/PostgreSQL fixtures only.
- Assert every recorded `chat_id`; a test must fail on an unexpected recipient.
- Find callback data through the visible button text instead of hard-coding database IDs.
- Disable `post_init` and the scheduler unless the scenario explicitly tests them.
- Add an explicit fixture response before exercising a new Bot API method. Unknown methods
  fail rather than silently succeeding.
- Never configure a production/debug bot token, production DB or club chat in this suite.

The suite enforces the last rule at runtime: it accepts only an in-memory SQLite URL and
obviously fake token, replaces socket connections with a failing stub, and requires every
`RecordingRequest` to declare its allowed private `chat_id` values. The transport rejects
an outbound call before recording it if the recipient is outside that allowlist. It also
checks the 4096-character message and 64-byte callback-data limits.

## Adversarial acceptance audit

The E2E project is not considered complete merely because the scenarios are green once.
After the five MVP flows land, perform and publish this audit in #270.

### 0. Stability

- Run the blocking job at least 20 consecutive times on GitHub-hosted runners without
  retries; any failure is investigated, not discarded as flaky.
- Track the check for 30 days. Target flaky rate is below 1%; one unexplained flaky failure
  blocks expansion of the suite.
- Ensure scenario order and repeated execution do not change the result.
- Keep network, wall-clock scheduling and shared fixtures out of the blocking suite.

### 1. Repository and CI cost

Report both test-process runtime and the complete GitHub job duration. The initial budgets
are:

- test process: at most 10 seconds for the five MVP flows;
- complete E2E job including checkout/install: at most 45 seconds with a warm pip cache;
- added PR critical-path latency: at most 15 seconds, since the E2E job runs in parallel
  with the ordinary suite;
- one shared harness, with no copy-pasted Bot API emulators per scenario.

If the job exceeds the budget, first remove duplicate setup and unnecessary fixtures.
Splitting into more runners is not a free optimization: it reduces latency but increases
billable minutes and maintenance.

### 2. Similarity to a real user run

Score each covered layer explicitly:

| Layer | In-process suite |
|---|---|
| PTB handler registration and pattern routing | yes |
| Telegram JSON parsing and callback context | yes |
| Bot method serialization, recipients and markup | yes |
| Handler/service/database side effects | yes, isolated DB |
| Telegram server validation | partial local limits only |
| Deployed process, polling and network | no |
| Telegram client rendering and tap behaviour | no |

Therefore this suite is a blocking **Telegram integration test**, not proof that the real
Telegram client renders the flow correctly. A small real smoke remains necessary.

### 3. Production isolation

- Prove from code and CI configuration that the suite uses a fake token, in-memory DB,
  network-deny guard and per-test schema/data.
- Search the job definition for production secrets and environment references; there must
  be none.
- Fail closed if isolation identity cannot be established.
- Real smoke, when added, uses only a dedicated test account, debug bot and disposable
  preview schema. It never opens a club chat and never has production DB credentials.

### 4. Video evidence

Do not call an animation generated from `RecordingRequest` a real Telegram video. It can be
a useful low-cost HTML storyboard, but it proves only what the fake transport already saw.

The preferred real-video experiment is a separate manual/nightly Playwright run against
Telegram Web with a dedicated test account. It should record a private-chat flow and upload
the video as a short-retention GitHub artifact. This job must stay non-blocking until its
session lifetime, flake rate, runtime and secret handling are measured. Expected trade-offs:

- closer to the user's visible UI than Telethon, which has no client rendering;
- materially slower and more fragile than the in-process suite;
- browser session state is a high-value secret and must never be committed or uploaded;
- videos may contain test data, so artifact access and retention must be restricted.

An Android emulator/Appium recording is closer to the mobile client but is likely too slow
and expensive for every PR. Evaluate it only if Telegram Web differs materially from the
actual target experience.

## Real Telegram smoke

The real post-deploy smoke described in
[#270](https://github.com/mmbabaev/MetaTheGathering/issues/270) is not implemented yet.
It will require a separate Telegram test account and debug-only secrets. Do not run a
second polling process with an existing bot token.
