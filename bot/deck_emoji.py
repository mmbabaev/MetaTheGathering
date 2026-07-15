# Эмодзи для архетипов колод.
# Поиск не зависит от регистра и лишних пробелов: игроки вводят названия руками, и в базе
# рядом живут «Jeskai Ephemerate» и «Jeskai ephemerate», «Rakdos Madness» и «Rakdos madness».
# Ключи ниже пишем в читаемом виде — регистр в них не важен.
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
    # ── Skred семейство ──────────────────────────────────────────────────
    "UR Skred": "🔴🔵🐍",
    "Red Skred": "🔴🧊",
    "Skred": "🔴🧊",
    # ── Jeskai ───────────────────────────────────────────────────────────
    "Jeskai Ephemerate": "🦁💧🔥",  # лев, вода, огонь — цвета клина (W/U/R)
}


def _key(deck_name: str) -> str:
    """Ключ поиска: без регистра и обрамляющих пробелов."""
    return deck_name.strip().lower()


# Индекс для поиска. Собирается один раз; ключи, различающиеся только регистром,
# схлопнулись бы молча, поэтому их запрещает тест.
_BY_KEY: dict[str, str] = {_key(name): emoji for name, emoji in _DECK_EMOJI.items()}


class DeckEmojiService:
    """Возвращает эмодзи для названия архетипа."""

    def get(self, deck_name: str) -> str:
        """Совпадение без учёта регистра → эмодзи. Иначе пустая строка."""
        return _BY_KEY.get(_key(deck_name), "")

    def format(self, deck_name: str) -> str:
        """'Red Kuldotha' → '🔴👺 Red Kuldotha', неизвестная → 'Unknown Deck'.

        Имя возвращаем как прислали: в кнопке должно стоять то, что ввёл игрок.
        """
        emoji = self.get(deck_name)
        if emoji:
            return f"{emoji} {deck_name}"
        return deck_name


deck_emoji = DeckEmojiService()
