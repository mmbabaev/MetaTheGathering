# Эмодзи для архетипов колод.
# Ключи — точные названия из базы (регистр важен).
# Для неизвестных колод возвращается пустая строка.

_DECK_EMOJI: dict[str, str] = {
    # ── Топ-10 по числу игроков ──────────────────────────────────────────
    "Blue Delver": "🔵🐍🪲",  # синий, змея, жук (Delver + Insectile Aberration)
    "Blue Faeries": "🔵🧚",  # синий, фея
    "Rakdos Madness": "🔴⚫👹",  # красный, чёрный, демон
    "Grixis Affinity": "🔴🔵⚫🤖🧊",  # три цвета, робот, холодильник
    "Dimir Faeries": "🔵⚫🧚",  # синий, чёрный, фея
    "Bogles": "🟢⚪😊",  # зелёный, белый, колобок (hexproof dude)
    "Red Kuldotha": "🔴👺",  # красный, гоблин
    "Dimir Terror": "🔵⚫💀🐍",  # синий, чёрный, череп, уж
    "Elves": "🟢🧝🧝‍♀️",  # зелёный, эльф, эльфийка
    "Caw Gates": "🔵⚪🦅⛩️",  # синий, белый, орёл, ворота
    # ── Расширенный список ───────────────────────────────────────────────
    "Red Rally": "🔴👥",
    "Mono Red Rally": "🔴👥",  # алиас
    "Red Burn": "🔴🔥",
    "Classic Burn": "🔴🔥",  # алиас
    "Mono Blue Faeries": "🔵🧚",
    "Dimir Control": "🔵⚫🧠",
    "Izzet Faeries": "🔴🔵🧚",
    "Izzet Control": "🔴🔵🧠",
    "Izzet Terror": "🔴🔵💀",
    "Azorius Familiars": "🔵⚪🦜",
    "Gruul Ramp": "🔴🟢🌿",
    "White Weenie": "⚪⚔️",
    "White Aggro": "⚪⚔️",  # алиас
    "Gardens": "🟢🌸",
    "Glee Combo": "🟢😄",
    "Jund Midrange": "🔴🟢⚫",
    "Cascade Tron": "🟡⚙️🪑",
    "Flicker Tron": "🟡✨🪑",
    "Tron": "🟡⚙️🪑",  # алиас
    "Red Tron": "🔴🟡⚙️🪑",
    "Gruul Tron": "🔴🟢⚙️🪑",
    "Moggwarts Combo": "🔴🧙",
    "Combo Walls": "🧱🔵",
    "Spy": "🕵️",
    "Spy Combo": "🕵️🔄",
    "Boros Synthesizer": "🔴⚪🤖",
    "Golgari Dredge": "🟢⚫🪦",
    # ── Blue Terror / Mono U семейство ───────────────────────────────────
    "Blue Terror": "🔵🐍🪲",
    "Mono U Terror": "🔵🐍🪲",
    "Mono U Delver": "🔵🐍🪲",
    "Mono Blue Delver": "🔵🐍🪲",
    "Mono Blue Terror": "🔵🐍🪲",
    # ── Madness семейство ────────────────────────────────────────────────
    "Red Madness": "🔴👹",
    "Mono Red Madness": "🔴👹",
    "Rakdos Reanimator": "🔴⚫💀👹",
    # ── Caw Gates алиасы ─────────────────────────────────────────────────
    "Caw-Gates": "🔵⚪🦅⛩️",
    # ── Jund / Wildfire ──────────────────────────────────────────────────
    "Jund Wildfire": "🔴🟢⚫🔥",
    "Gruul Ponza": "🔴🟢🪨",
    "Gruul Rhino Friends + Eldrazi": "🔴🟢🦏",
}


class DeckEmojiService:
    """Возвращает эмодзи для названия архетипа."""

    def get(self, deck_name: str) -> str:
        """Точное совпадение → эмодзи. Иначе пустая строка."""
        return _DECK_EMOJI.get(deck_name, "")

    def format(self, deck_name: str) -> str:
        """'Red Kuldotha' → '🔴👺 Red Kuldotha', неизвестная → 'Unknown Deck'."""
        emoji = self.get(deck_name)
        if emoji:
            return f"{emoji} {deck_name}"
        return deck_name


deck_emoji = DeckEmojiService()
