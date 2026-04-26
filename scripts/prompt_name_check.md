# Prompt: detect wrong first_name / last_name order

## Context

This is a list of Russian players from a Magic: The Gathering bot database.
Each row: `id,first_name,last_name`

The database stores names in two separate columns:
- `first_name` — should contain the **given name** (Имя), e.g. Иван, Дмитрий, Мария
- `last_name` — should contain the **surname** (Фамилия), e.g. Иванов, Петрова, Козлов

Some users entered their name in the wrong order: they put the surname in `first_name` and the given name in `last_name`. These need to be swapped.

## Task

Go through each row. For each row, decide:
- Is `first_name` actually a given name and `last_name` actually a surname? → **OK**, do nothing.
- Is `first_name` actually a surname and `last_name` actually a given name? → **SWAP**, include the id in the result.

## Rules

- Focus on Russian names. Surnames typically end in: -ов/-ев/-ин/-ский/-цкий/-енко/-ко/-ых/-ая/-ова/-ева etc. Given names: Иван, Дмитрий, Александр, Сергей, Михаил, Николай, Алексей, Андрей, Мария, Наталья, etc.
- When uncertain — skip (do not include in the result).
- Ignore rows where the name is clearly test data (e.g. "Тест1", digits, etc.).

## Output format

Return ONLY a plain list of IDs to swap, one per line. No explanations, no headers.
Example:
```
32
33
78
```

## Data

```
{PASTE CSV HERE}
```
