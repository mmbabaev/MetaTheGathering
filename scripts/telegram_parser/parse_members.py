"""
Parse members of a Telegram chat and print their names and usernames.

Usage:
    python parse_members.py <chat>

    <chat> can be a username (@groupname), invite link, or numeric chat ID.

Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in .env (same directory or project root).
A session file (session.session) will be created on first run — keep it out of git.
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import ChatAdminRequiredError, UsernameNotOccupiedError

# Load .env from this script's directory, then fall back to project root
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent.parent / ".env")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_NAME = Path(__file__).parent / "session"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List members of a Telegram chat")
    parser.add_argument("chat", help="Chat username (@name), invite link, or numeric ID")
    return parser.parse_args()


async def main(chat: str) -> None:
    if not API_ID or not API_HASH:
        sys.exit("Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")

    client = TelegramClient(str(SESSION_NAME), int(API_ID), API_HASH)

    async with client:
        await client.start()

        try:
            members = []
            async for user in client.iter_participants(chat):
                full_name = " ".join(
                    part for part in (user.first_name, user.last_name) if part
                ).strip() or "<no name>"

                username = f"@{user.username}" if user.username else "(no username)"
                members.append((full_name, username, user.id))

        except ChatAdminRequiredError:
            sys.exit("Error: you need admin rights to list members of this chat")
        except UsernameNotOccupiedError:
            sys.exit(f"Error: chat '{chat}' not found")
        except ValueError as e:
            sys.exit(f"Error: {e}")

    print(f"{'Name':<40} {'Username':<25} {'ID'}")
    print("-" * 75)
    for full_name, username, user_id in members:
        print(f"{full_name:<40} {username:<25} {user_id}")

    print(f"\nTotal: {len(members)} members")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.chat))
