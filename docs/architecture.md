# Stack

# Основа
python-telegram-bot>=20.0  # Async API
sqlalchemy                  # ORM для БД
alembic                     # Миграции
pydantic                    # Валидация данных

# База данных
postgresql                  # Основная БД
redis (optional)            # Кэш для быстрых обновлений

# Деплой
docker + docker-compose



# Files structure

metascrabber/
├── bot/
│   ├── handlers/
│   │   ├── player.py      # Регистрация, выбор колоды
│   │   ├── voting.py      # Голосование
│   │   ├── admin.py       # Админ-панель
│   │   └── common.py      # /start, /help
│   ├── keyboards/         # Inline клавиатуры
│   ├── messages/          # Шаблоны сообщений
│   └── middlewares/       # Проверка прав, логирование
├── core/
│   ├── models.py          # SQLAlchemy модели
│   ├── schemas.py         # Pydantic схемы
│   ├── database.py        # Подключение к БД
│   └── config.py          # Настройки
├── services/
│   ├── tournament.py      # Логика турниров
│   ├── voting.py          # Логика голосования
│   ├── export.py          # Выгрузка данных
│   └── stats.py           # Статистика
├── utils/
│   ├── formatters.py      # Форматирование таблиц
│   └── validators.py      # Валидация ввода
├── web/                   # Будущий веб-интерфейс
│   └── api/               # REST API (FastAPI)
├── alembic/               # Миграции БД
├── main.py                # Точка входа
└── docker-compose.yml


