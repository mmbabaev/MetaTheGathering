from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import settings

engine = create_engine(
    settings.DATABASE_URL.unicode_string(),
    echo=settings.DEBUG,
    future=True,
    # Соединение к Postgres может тихо отвалиться (перезапуск БД, таймаут файрвола).
    # Раньше это било реже — сессия была одна и жила долго; теперь их много и они короткие,
    # так что дешёвая проверка перед выдачей соединения из пула важнее.
    pool_pre_ping=True,
)

# Сессия на задачу, а не на поток. Бот асинхронный и живёт в одном потоке: с
# scoped_session ВСЕ задачи (импорт, джобы, нажатия кнопок, веб-запросы) делили один
# объект сессии, и `db.close()` в finally любой из них закрывал сессию всем остальным —
# включая тех, кто в этот момент висел на await. Отсюда терялись записи, сделанные после
# await: объект оказывался detached, commit проходил вхолостую и без ошибки (так пришёл
# дубль отбивки «сбор метагейма завершён», PR #169).
#
# Scoped-семантика проекту и не нужна: `SessionLocal.remove()` не вызывается нигде, весь
# код уже написан в стиле «открыл → закрыл в finally», то есть в расчёте на свою сессию.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

Base = declarative_base()


def get_db():
    """Заготовка для DI (FastAPI / хендлеры бота)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
