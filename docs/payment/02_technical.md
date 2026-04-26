# Техническая реализация — Онлайн-оплата в Telegram-боте

## Стек

- **Бот:** Python (python-telegram-bot)
- **Платёжная система:** ЮKassa
- **Вебхук-сервер:** Flask или FastAPI
- **Хостинг:** существующий VPS где уже крутится бот

---

## Структура проекта

```
bot/
  payments/
    yookassa_client.py     # создание платежа
    webhook_handler.py     # получение уведомлений
  handlers/
    pay.py                 # команда /pay в боте
  db/
    players.py             # отметить игрока как оплатившего
```

---

## Что нужно получить от клуба

- `ShopID` — публичный идентификатор магазина в ЮKassе
- `Secret Key` — приватный ключ

Это две строки которые владелец находит в личном кабинете ЮKassы → Интеграция → API ключи.

---

## Код

### 1. Создание платежа

```python
# payments/yookassa_client.py
import requests
import uuid

SHOP_ID = "ваш_shop_id"
SECRET_KEY = "ваш_secret_key"

def create_payment(amount: float, player_name: str, tournament_name: str, telegram_id: int) -> str:
    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        json={
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/ваш_бот"
            },
            "description": f"{tournament_name} — {player_name}",
            "metadata": {
                "telegram_id": telegram_id,
                "tournament": tournament_name
            },
            "capture": True
        },
        auth=(SHOP_ID, SECRET_KEY),
        headers={"Idempotence-Key": str(uuid.uuid4())}
    )
    data = response.json()
    return data["confirmation"]["confirmation_url"]
```

### 2. Команда /pay в боте

```python
# handlers/pay.py
async def pay_handler(update, context):
    player_name = update.effective_user.full_name
    telegram_id = update.effective_user.id

    url = create_payment(
        amount=525.00,
        player_name=player_name,
        tournament_name="MTG Standard 26 апреля",
        telegram_id=telegram_id
    )

    await update.message.reply_text(
        f"💳 Оплата взноса — 525 руб.\n\n"
        f"Ссылка действует 1 час:\n{url}\n\n"
        f"После оплаты ты автоматически появишься в списке участников."
    )
```

### 3. Webhook — уведомление об оплате

```python
# payments/webhook_handler.py
from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook/yookassa", methods=["POST"])
def yookassa_webhook():
    data = request.json

    if data["event"] == "payment.succeeded":
        payment = data["object"]
        telegram_id = payment["metadata"]["telegram_id"]
        tournament = payment["metadata"]["tournament"]
        amount = payment["amount"]["value"]

        # Помечаем игрока как оплатившего
        mark_player_as_paid(telegram_id, tournament)

        # Уведомляем игрока
        bot.send_message(
            telegram_id,
            f"✅ Оплата {amount} руб. получена! Ты в списке турнира."
        )

    return {"status": "ok"}, 200
```

---

## Настройка со стороны клуба

1. Зарегистрироваться на [yookassa.ru](https://yookassa.ru)
2. Указать ИП или ООО, загрузить документы (1-3 дня на проверку)
3. В личном кабинете → Интеграция → скопировать ShopID и Secret Key
4. Отправить тебе эти два значения
5. В настройках ЮKassы указать URL вебхука: `https://твой-сервер.ru/webhook/yookassa`

---

## Тестирование

ЮKassa выдаёт тестовые ключи — можно гонять платежи без реальных денег.

**Тестовая карта:**
- Номер: `4111 1111 1111 1111`
- CVV: любой
- Дата: любая в будущем

### Чеклист перед запуском

- [ ] Бот присылает ссылку на оплату по команде /pay
- [ ] Ссылка открывается, форма оплаты работает
- [ ] После оплаты редиректит обратно в бот
- [ ] Webhook получает уведомление
- [ ] Бот пишет игроку "✅ оплата получена"
- [ ] В кабинете ЮKassы виден платёж с правильным описанием ("MTG Standard 26 апреля — Иванов Михаил")
- [ ] Игрок появляется в списке участников турнира

---

## Публичный URL для вебхука

Вебхук требует публичный HTTPS-адрес.

- **Если есть VPS** — просто поднять Flask/FastAPI на том же сервере где бот
- **Для тестирования локально** — использовать [ngrok](https://ngrok.com): `ngrok http 5000`

---

## Дальнейшее масштабирование

Чтобы добавить новый тип турнира или новый клуб — только добавить новые ключи и новый `tournament_name`. Архитектура не меняется.
