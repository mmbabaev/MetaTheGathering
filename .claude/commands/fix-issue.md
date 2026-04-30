# Fix GitHub Issue

Когда пользователь просит исправить issue — выполни этот workflow по шагам, не пропуская шаг 3 (план).

## Шаг 1. Изучи issue и создай ветку (одно одобрение)

Используй скрипт `scripts/dev/start-issue.sh` — он читает issue, пуллит main и создаёт ветку за одно одобрение:

```bash
# Последний открытый issue:
bash scripts/dev/start-issue.sh

# Или конкретный:
bash scripts/dev/start-issue.sh <NUMBER>
```

Если нужно выбрать из нескольких — сначала посмотри список:
```bash
gh issue list --state open --limit 20
```

## Шаг 3. Изучи код и ОБЪЯСНИ ПЛАН

**До написания кода** — исследуй файлы, найди корень бага, затем напиши пользователю:
- **Что происходит сейчас** — опиши проблему своими словами, как она проявляется
- **Почему** — корень бага в коде (файл, строка, логика)
- **Что меняем** — какие файлы и как именно
- **Тесты** — что проверяем

**Жди подтверждения от пользователя.** Не переходи к шагу 4 без явного «да» / «ок» / «давай».

## Шаг 4. Реализуй фикс

Создай ветку и застейдж файлы:
```bash
git checkout -b fix/<slug>
# ... правки кода ...
git add <файлы>
```

Запусти тесты и линтер (два одобрения):
```bash
python3 -m pytest tests/ -q
python3 -m ruff check . && python3 -m ruff format .
```

## Шаг 5. Создай PR (одно одобрение)

Используй скрипт `scripts/dev/create-pr.sh` — он делает commit + push + gh pr create за одно одобрение:

```bash
bash scripts/dev/create-pr.sh \
  "fix/<slug>" \
  "fix: <описание> (#<issue>)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>" \
  "fix: <pr title>" \
  "## Summary
- <bullet>

## Test plan
- [ ] <test>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Выведи URL PR пользователю.

## Шаг 6. Проверь CI (одно одобрение, ~90с ожидания)

Используй скрипт `scripts/dev/check-ci.sh` — он ждёт и проверяет за одно одобрение:

```bash
bash scripts/dev/check-ci.sh <PR_NUMBER> 90
```

Сообщи результат: pass / fail. Если fail — прочитай логи и исправь.
