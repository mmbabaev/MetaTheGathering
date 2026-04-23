# Aetherhub Parser Implementation

## Summary

Successfully implemented support for **two different Aetherhub tournament formats** with automatic format detection.

## Files Created

### Core Implementation
1. **[`services/aetherhub_models.py`](../../services/aetherhub_models.py)** - Data models (moved from main service)
   - `AetherhubPairing` - Single player-opponent pairing
   - `AetherhubRound` - Round with list of pairings
   - `AetherhubTournamentData` - Complete tournament data

2. **[`services/aetherhub_parser_edinorog.py`](../../services/aetherhub_parser_edinorog.py)** - Format 1 parser
   - Parses tournaments with embedded HTML pairings
   - Uses `?p=X` URL parameters for rounds
   - Example: https://aetherhub.com/Tourney/RoundTourney/98984

3. **[`services/aetherhub_parser_js_format.py`](../../services/aetherhub_parser_js_format.py)** - Format 2 parser
   - Parses tournaments with JavaScript-loaded pairings
   - Uses API endpoint: `/Tourney/RoundTourneyPublicPairings?id={id}&round={n}`
   - Example: https://aetherhub.com/Tourney/RoundTourney/99024

4. **[`services/aetherhub.py`](../../services/aetherhub.py)** - Main service with auto-detection
   - Automatically detects tournament format
   - Routes to appropriate parser
   - Maintains backward compatibility

### Tests
- **[`tests/test_aetherhub_js_format.py`](../../tests/test_aetherhub_js_format.py)** - 15 tests for JS format parser
- **[`tests/test_aetherhub.py`](../../tests/test_aetherhub.py)** - 47 existing tests (all passing)
- **Total: 62 tests, all passing ✅**

### Research Files (in this directory)
- `AETHERHUB_FORMATS.md` - Detailed analysis of both formats
- `aetherhub_test.py` - Original edinorog format test
- `aetherhub_test_99024.py` - JS format basic test
- `aetherhub_test_99024_detailed.py` - JS format detailed analysis
- `aetherhub_find_api.py` - API endpoint discovery script
- `aetherhub_test_pairings_api.py` - API endpoint testing
- `aetherhub_parse_pairings.py` - Working parser example
- `aetherhub_*.html` - Saved HTML for analysis
- `pairings_round_*.html` - API responses for each round

## Format Detection

The main service automatically detects which format to use by checking:
```python
def _detect_tournament_format(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    pairings_tab = soup.find("div", {"id": "tab_pairings"})
    
    if pairings_tab is not None:
        has_data_page = pairings_tab.get("data-page") is not None
        is_empty = len(pairings_tab.find_all("table")) == 0
        
        if has_data_page and is_empty:
            return "js"  # JavaScript format
    
    return "edinorog"  # Embedded HTML format
```

## Usage

The API remains unchanged for consumers:

```python
from services.aetherhub import fetch_tournament

# Works with both formats automatically
tournament_data = fetch_tournament("https://aetherhub.com/Tourney/RoundTourney/99024")

print(f"Players: {len(tournament_data.players)}")
print(f"Rounds: {len(tournament_data.rounds)}")

for round in tournament_data.rounds:
    print(f"Round {round.number}: {len(round.pairings)} pairings")
```

## API Endpoint Discovery

The key breakthrough was finding the JavaScript API endpoint:
```
https://aetherhub.com/Tourney/RoundTourneyPublicPairings?id={tournament_id}&round={round_num}
```

This endpoint returns HTML tables that can be parsed without JavaScript execution, avoiding the need for Selenium or browser automation.

## Key Features

✅ **Automatic format detection** - No manual configuration needed
✅ **Both formats supported** - Edinorog and JS formats  
✅ **No browser automation** - Uses direct API calls
✅ **Backward compatible** - Existing code continues to work
✅ **Fully tested** - 62 tests covering both formats
✅ **Clean architecture** - Separate parser classes

## Test Results

```bash
$ python3 -m pytest tests/test_aetherhub.py tests/test_aetherhub_js_format.py -v
...
====== 62 passed in 0.36s ======
```

All tests passing, including:
- Format detection
- Player extraction
- Pairing parsing (including byes)
- Round navigation
- Tournament import
- Backward compatibility

## Future Improvements

1. Add caching for API responses
2. Add retry logic for network errors
3. Consider adding format detection logs for monitoring
4. Add integration tests with real tournament URLs (if appropriate)

## Conclusion

The implementation successfully supports both Aetherhub tournament formats with automatic detection, maintaining full backward compatibility while adding robust new functionality. The parser architecture is clean, testable, and extensible.
