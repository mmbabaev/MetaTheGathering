class FeatureService:
    def __init__(self, debug: bool = False) -> None:
        self._debug = debug

    def can_fill_opponent_decks(self) -> bool:
        return self._debug
