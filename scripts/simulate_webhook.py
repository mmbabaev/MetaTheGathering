"""
Simulate a YooKassa payment.succeeded webhook for local testing.

Usage:
  1. Create a payment via the bot (get yookassa_payment_id from DB or logs)
  2. Run: python scripts/simulate_webhook.py <yookassa_payment_id>

  Or test without a real payment (creates a fake record if the ID exists in DB):
  python scripts/simulate_webhook.py test_fake_id_123
"""

import sys
import uuid

import requests

WEBHOOK_URL = "http://localhost:8080/webhook/yookassa"


def build_payload(yookassa_payment_id: str) -> dict:
    return {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": yookassa_payment_id,
            "status": "succeeded",
            "amount": {"value": "525.00", "currency": "RUB"},
            "description": "Test payment",
            "metadata": {},
            "payment_method": {"type": "bank_card"},
        },
    }


def main() -> None:
    payment_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    payload = build_payload(payment_id)

    print(f"Sending webhook to {WEBHOOK_URL}")
    print(f"payment_id: {payment_id}")

    resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")


if __name__ == "__main__":
    main()
