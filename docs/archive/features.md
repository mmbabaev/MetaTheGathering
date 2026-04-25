1. Умное определение архетипа
python
# Если игрок пишет "афинити" или "affi"
archetypes = {
    "Affinity": ["affinity", "affi", "афинити", "аффинити"],
    "Burn": ["burn", "red deck wins", "rdw", "берн"],
    # ...
}

2. Анти-спам при голосовании
Игрок может изменить свой голос
Но не чаще 1 раза в 30 секунд на одного участника
Нельзя голосовать за свою колоду
3. Система подтверждений
text
Статус колоды определяется:
- ✓ Подтверждена: upvotes - downvotes >= 3
- ⚠️ Спорная: |upvotes - downvotes| < 3
- ✗ Ошибочна: downvotes - upvotes >= 3
4. Форматы выгрузки
CSV для анализа:
text
Date,Player,Archetype,Upvotes,Downvotes,Status,Place
2026-01-31,player1,Burn,5,0,confirmed,1
2026-01-31,player2,Affinity,4,1,confirmed,2
Markdown для постов:
text
# MTG Pauper Meta Report - 31.01.2026

## Breakdown
- **Burn**: 7 players (29%)
- **Affinity**: 5 players (21%)
- **Faeries**: 4 players (17%)
...
JSON для веб-сайта:
json
{
  "tournament_id": "2026-01-31",
  "total_players": 24,
  "archetypes": [
    {"name": "Burn", "count": 7, "percentage": 29.2},
    ...
  ]
}
Безопасность и права
python
# Три роли
ROLES = {
    "superadmin": [...],  # Создание турниров, назначение админов
    "admin": [...],       # Управление текущим турниром
    "player": [...]       # Регистрация, голосование
}

# Проверка в middleware
@admin_required
async def edit_deck(update, context):
    ...