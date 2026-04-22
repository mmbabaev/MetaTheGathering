from dataclasses import dataclass

FIELD_DECK_NAME = "koloda_igroka_b1uy"
FIELD_MATCHES = "ff8d7ec0-856c-11ef-8901-6fb67336f168"
FIELD_WINRATE = "8dd98d80-8569-11ef-90c9-2999d49d0630"


@dataclass
class DeckStats:
    name: str
    matches: int
    winrate: float

    def __repr__(self) -> str:
        return f"DeckStats(name={self.name!r}, matches={self.matches}, winrate={self.winrate:.1f}%)"


class PlayerChoicesResponse:
    def __init__(self, response: dict):
        self._rows = response["data"]["rows"]

    def decks(self) -> list[DeckStats]:
        result = []
        for row in self._rows:
            cells = {cell["fieldId"]: cell["value"] for cell in row["cells"]}
            result.append(
                DeckStats(
                    name=cells[FIELD_DECK_NAME],
                    matches=int(cells[FIELD_MATCHES]),
                    winrate=float(cells[FIELD_WINRATE]),
                )
            )
        return result
