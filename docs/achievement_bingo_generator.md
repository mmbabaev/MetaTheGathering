# Bingo generator: preview contract

Первый кодовый slice issue [#213](https://github.com/mmbabaev/MetaTheGathering/issues/213)
реализует этапы A–B: versioned manifest, конкретные candidates, fixture-каталог и
детерминированный pure generator. Здесь ещё нет БД, Season/Board/Cell, Board Lab route,
player UI, сохранения completion events или prize claims.

## Поток данных

```text
AchievementTypeManifest
  -> параметризация для season + player
  -> InstantiatedCandidate (frozen params + eligibility)
  -> generate_board(..., seed, constraints)
  -> BoardDraft (16 cells + reproducible input + diagnostics)
```

Контракты находятся в `services/achievements/bingo/models.py`, solver — в
`generator.py`, pure-параметризаторы — в `parameterizers.py`, временный каталог для
четырёх fairness-personas — в `fixtures.py`.

## Инварианты v1

- размер 4×4 и квоты `4 easy / 6 medium / 4 hard / 2 rare`;
- в каждом горизонтальном ряду минимум одна easy и один маршрут без требования
  высокого baseline-винрейта;
- максимум одна rare и одна peer-confirmed клетка на ряд;
- максимум две peer-confirmed клетки на поле;
- один конкретный opponent не встречается больше одного раза;
- одна mechanic не дублируется под разными candidate IDs;
- incompatibilities и `max_per_board` проверяются до добавления клетки;
- candidate с `eligible=false`, `idea` или `data_blocked` не попадает на поле и остаётся
  в diagnostics с reason/fallback;
- невозможный pool завершает ограниченный backtracking с `BoardGenerationError`, а не
  уходит в случайный reroll.

Алгоритм использует SHA-256 ranking от `algorithmVersion + catalogVersion + seasonId +
playerId + seed`. Порядок candidates на входе не влияет на результат. `BoardDraft.stable_json()`
возвращает canonical JSON, а input содержит fingerprint полного candidate pool.

## Fixture-каталог

`PREVIEW_MANIFESTS` содержит больше 20 механик из #200/#214 со статусом
`ready_for_preview`. `fixture_candidates()` параметризует их для четырёх профилей:
новичок, любитель, регуляр и про. У новичка stats/H2H candidates без baseline явно
отклоняются; database fallback остаётся в пуле той же сложности.

Версия `board-lab-fixtures-v2` добавляет production-shaped механику `play_deck` из
[#200](https://github.com/mmbabaev/MetaTheGathering/issues/200). Она превращает frozen
top-deck catalog в несколько конкретных candidates с одной mechanic: каждая клетка хранит
`statsSnapshotId`, точную `deckGeneralName`, rank и размер baseline, а игрок видит ручное
флейворное название и условие «Сыграй турнир на колоде X». Solver может выбрать один из
вариантов, но не поставит два `play_deck` на одно поле. Pure completion evaluator сравнивает
только canonical `general_name`; пользовательский display name не засчитывается как скрытая
эвристика. Пустой catalog создаёт auditable rejected candidate с reason
`no_frozen_deck_targets` и fallback на `try_new_deck`, а не исчезает из diagnostics молча.

Fixtures нужны только для Board Lab и fairness-тестов. Они не являются утверждённым pool
первого сезона и не должны активироваться как production boards. Перед activation нужны
решения #215, frozen stats provider #211 и persistence/events/claims #212.

Пример preview-поля каталога v1 для персоны «Регуляр», seed `42`:

![Bingo board preview](assets/bingo-board-preview-seed-42.png)

Дополнительные варианты той же персоны с другими seeds:

![Bingo board preview seed 43](assets/bingo-board-preview-seed-43.jpg)

![Bingo board preview seed 44](assets/bingo-board-preview-seed-44.jpg)

![Bingo board preview seed 45](assets/bingo-board-preview-seed-45.jpg)

## Проверка

```bash
python3 -m pytest tests/test_achievement_bingo_generator.py -q
```

Тесты строят 100 seeds для каждой из четырёх personas, проверяют квоты/ряды,
детерминированность, независимость от входного порядка, no-data diagnostics, конкретную
параметризацию/проверку `play_deck` и явную ошибку для невыполнимого pool.
