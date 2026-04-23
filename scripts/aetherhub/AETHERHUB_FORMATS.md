# Aetherhub Tournament Format Analysis

## Overview
There are TWO different tournament formats on Aetherhub that need different parsing approaches.

## Format 1: "Edinorog Format" (Tournament 98984)
- **URL**: https://aetherhub.com/Tourney/RoundTourney/98984
- **Test File**: [`scripts/aetherhub_test.py`](scripts/aetherhub_test.py)
- **Characteristic**: Pairings and results are embedded in the HTML

### HTML Structure
- Pairings are available directly in the HTML tables
- Can be parsed using BeautifulSoup from the initial page load
- No JavaScript execution required

## Format 2: "Dynamic Format" (Tournament 99024)
- **URL**: https://aetherhub.com/Tourney/RoundTourney/99024  
- **Test File**: [`scripts/aetherhub_test_99024.py`](scripts/aetherhub_test_99024.py)
- **Characteristic**: Pairings load dynamically via JavaScript

### HTML Structure
```html
<div class="tab-pane active" id="tab_pairings" data-page="4">
    <!-- Empty - content loaded by JavaScript -->
</div>
```

### Key Findings
1. **Pairings Tab**: Empty in HTML, has `data-page="4"` attribute indicating current round
2. **JavaScript**: Uses `tourney-roundtourneypublic.js` to load pairings dynamically
3. **Standings Table**: Available in HTML with rich player data attributes:
   - `data-name`: Player name
   - `data-matchwins`: Number of match wins
   - `data-roundsplayed`: Total rounds (games) played
   - `data-roundswon`: Total rounds (games) won
   - `data-pointpotential`: Maximum possible points
   - `data-byes`: Number of byes
   - `data-draws`: Number of draws

### Players Extracted
Successfully extracted 25 players from standings table:
1. Старостин Владислав
2. Емельянов Илья
3. Бабаев Михаил
4. (and 22 more...)

## Data Models

Created [`services/aetherhub_models.py`](services/aetherhub_models.py) with:

```python
@dataclass
class AetherhubPairing:
    player: str
    opponent: str | None  # None = bye

@dataclass
class AetherhubRound:
    number: int
    pairings: list[AetherhubPairing]

@dataclass
class AetherhubTournamentData:
    url: str
    players: list[str]  # from round 1 standings
    rounds: list[AetherhubRound]
```

## Next Steps for Format 2 Parsing

### Option 1: Browser Automation (Selenium/Playwright)
- Execute JavaScript to load pairings
- Extract content after page fully loads
- **Pros**: Gets actual pairing data
- **Cons**: Slower, requires browser driver

### Option 2: Reverse Engineer API
- Analyze `tourney-roundtourneypublic.js` to find API endpoint
- Make direct HTTP requests to pairing endpoint
- **Pros**: Fast, efficient
- **Cons**: Need to find and understand endpoint

### Option 3: Use Existing Data
- Parse player match history from standings attributes
- Reconstruct pairings from results
- **Pros**: No additional requests needed
- **Cons**: May not get exact round-by-round pairings, only final results

### Option 4: Hybrid Approach
- Use standings for player list
- For completed tournaments, parse results from standings data
- For active tournaments, use browser automation or API

## Files Created

1. **[`services/aetherhub_models.py`](services/aetherhub_models.py)** - Data models
2. **[`scripts/aetherhub_test.py`](scripts/aetherhub_test.py)** - Format 1 test (edinorog)
3. **[`scripts/aetherhub_test_99024.py`](scripts/aetherhub_test_99024.py)** - Format 2 basic test
4. **[`scripts/aetherhub_test_99024_detailed.py`](scripts/aetherhub_test_99024_detailed.py)** - Format 2 detailed analysis
5. **[`scripts/aetherhub_99024.html`](scripts/aetherhub_99024.html)** - Saved HTML for inspection

## Recommendations

For the MetaGatherer project:

1. **Start with Format 1** - Implement full parsing for edinorog format first
2. **Players Only for Format 2** - Initially just extract player list from standings
3. **Future Enhancement** - Add browser automation or API reverse engineering for pairings

This approach allows incremental implementation while supporting both tournament types.
