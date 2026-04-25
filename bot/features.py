class FeatureService:
    def __init__(self, debug: bool = False) -> None:
        self._debug = debug

    def opponents_for_all(self) -> bool:
        return self._debug
