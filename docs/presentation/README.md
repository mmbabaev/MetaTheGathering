# MetaGatherer — короткая презентация

Готовый файл: `MetaGatherer_short_ru.pptx` (6 слайдов, 16:9, редактируемый PowerPoint).

Подробная версия: `MetaGatherer_detailed_ru.pptx` (13 слайдов).

Видео-демо: `MetaGatherer_demo_ru.mp4` (слайдшоу с поясняющими титрами, без звука).

Сборка:

```bash
python3 -m pip install --target /private/tmp/metagatherer-presentation python-pptx
PYTHONPATH=/private/tmp/metagatherer-presentation python3 docs/presentation/build_presentation.py
PYTHONPATH=/private/tmp/metagatherer-presentation python3 docs/presentation/build_detailed.py
```

## Происхождение материалов

- `github-meta-reference.png` — вложение из GitHub issue #126, посвящённого графику метагейма.
- `real-*.jpg/png/jpeg` — реальные кадры Telegram Desktop и готовые изображения из материалов,
  переданных автором проекта 31 июля 2026 года.
- `architecture-flow.png` — верхнеуровневая схема полного сценария турнира.
- `bot-avatar.png` — аватар бота, извлечённый из реального Telegram-скриншота.
- `card-*.jpg` — изображения реальных MTG-карт Tolarian Terror и Experimental Synthesizer,
  полученные через Scryfall; `mtg-card-pair.png` — композиция для видео.
- `telegram-*.png` — запасные реконструкции по актуальным строкам и клавиатурам из
  `bot/messages/` и `bot/keyboards/`; в текущей версии слайдов не используются.
- Метрика `513 / 514` и `145 архетипов` — из `docs/meta_chart.md`.
- Архитектурная схема — по фактическим слоям проекта и интеграциям в `services/`.

Файлы в `assets/` можно заменить настоящими обезличенными Telegram-скриншотами и повторно
запустить сборку.
