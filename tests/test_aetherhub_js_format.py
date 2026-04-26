"""Tests for Aetherhub JS format parser."""

from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup

from services.aetherhub_models import AetherhubPairing, AetherhubRound, AetherhubTournamentData
from services.aetherhub_parser_js_format import AetherhubJSFormatParser


class TestAetherhubJSFormatParser:
    """Test suite for AetherhubJSFormatParser."""

    @pytest.fixture
    def parser(self):
        """Create parser instance with mock scraper."""
        mock_scraper = Mock()
        return AetherhubJSFormatParser(scraper=mock_scraper)

    def test_extract_tournament_id(self, parser):
        """Test extracting tournament ID from URL."""
        url = "https://aetherhub.com/Tourney/RoundTourney/99024"
        tournament_id = parser._extract_tournament_id(url)
        assert tournament_id == "99024"

    def test_extract_tournament_id_invalid(self, parser):
        """Test error handling for invalid URL."""
        with pytest.raises(ValueError, match="Cannot extract tournament ID"):
            parser._extract_tournament_id("https://example.com/invalid")

    def test_extract_player_name_with_points(self, parser):
        """Test extracting player name from text with points at the end."""
        text = "Старостин Владислав (9 Points)"
        name = parser._extract_player_name(text)
        assert name == "Старостин Владислав"

    def test_extract_player_name_with_points_in_middle(self, parser):
        """Test extracting player name when points label is between first and last name."""
        assert parser._extract_player_name("Валентин (6 Points) Задорожний") == "Валентин Задорожний"
        assert parser._extract_player_name("Иван (3 Points) Юров") == "Иван Юров"
        assert parser._extract_player_name("Илья (9 Points) Емельянов") == "Илья Емельянов"

    def test_extract_player_name_without_points(self, parser):
        """Test extracting player name from plain text."""
        text = "Емельянов Илья"
        name = parser._extract_player_name(text)
        assert name == "Емельянов Илья"

    def test_extract_player_name_empty(self, parser):
        """Test extracting player name from empty text."""
        assert parser._extract_player_name("") is None
        assert parser._extract_player_name(None) is None
        assert parser._extract_player_name("   ") is None

    def test_extract_player_name_bye(self, parser):
        """Test that BYE is treated as None."""
        assert parser._extract_player_name("BYE") is None
        assert parser._extract_player_name("bye") is None
        assert parser._extract_player_name("BYE (0 Points)") is None
        assert parser._extract_player_name("Bye (0 Points)") is None

    def test_players_from_round(self, parser):
        """Test extracting unique players from round 1 pairings."""
        round_data = AetherhubRound(
            number=1,
            pairings=[
                AetherhubPairing(player="Player One", opponent="Player Two"),
                AetherhubPairing(player="Player Two", opponent="Player One"),
                AetherhubPairing(player="Player Three", opponent=None),
            ],
        )
        players = parser._players_from_round(round_data)
        assert players == ["Player One", "Player Two", "Player Three"]

    def test_players_from_round_preserves_order(self, parser):
        """Test that player order from round 1 pairings is preserved."""
        round_data = AetherhubRound(
            number=1,
            pairings=[
                AetherhubPairing(player="Charlie", opponent="Alice"),
                AetherhubPairing(player="Alice", opponent="Charlie"),
                AetherhubPairing(player="Bob", opponent=None),
            ],
        )
        players = parser._players_from_round(round_data)
        assert players == ["Charlie", "Alice", "Bob"]

    def test_parse_num_rounds_from_span(self, parser):
        """Test parsing number of rounds from numberOfRounds span."""
        html = '<span id="numberOfRounds">Rounds 4</span>'
        soup = BeautifulSoup(html, "html.parser")
        num_rounds = parser._parse_num_rounds(soup)
        assert num_rounds == 4

    def test_parse_num_rounds_from_data_page(self, parser):
        """Test parsing number of rounds from data-page attribute."""
        html = '<div id="tab_pairings" data-page="5"></div>'
        soup = BeautifulSoup(html, "html.parser")
        num_rounds = parser._parse_num_rounds(soup)
        assert num_rounds == 5

    def test_parse_num_rounds_default(self, parser):
        """Test default number of rounds when no data available."""
        html = "<div>No round info</div>"
        soup = BeautifulSoup(html, "html.parser")
        num_rounds = parser._parse_num_rounds(soup)
        assert num_rounds == 4  # Default

    def test_parse_round_with_pairings(self, parser):
        """Test parsing a round with pairings."""
        html = """
        <table id="matchList">
            <tbody>
                <tr>
                    <td>1</td>
                    <td>Player One (9 Points)</td>
                    <td>Player Two (6 Points)</td>
                </tr>
                <tr>
                    <td>2</td>
                    <td>Player Three (3 Points)</td>
                    <td>Player Four (3 Points)</td>
                </tr>
            </tbody>
        </table>
        """

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        parser.scraper.get.return_value = mock_response

        round_data = parser._parse_round("99024", 1)

        assert round_data is not None
        assert round_data.number == 1
        assert len(round_data.pairings) == 4  # 2 matches × 2 directions

        # Check bidirectional pairings
        pairing_dict = {p.player: p.opponent for p in round_data.pairings}
        assert pairing_dict["Player One"] == "Player Two"
        assert pairing_dict["Player Two"] == "Player One"
        assert pairing_dict["Player Three"] == "Player Four"
        assert pairing_dict["Player Four"] == "Player Three"

    def test_parse_round_with_bye(self, parser):
        """Test parsing a round with a bye."""
        html = """
        <table id="matchList">
            <tbody>
                <tr>
                    <td>1</td>
                    <td>Player One (9 Points)</td>
                    <td></td>
                </tr>
            </tbody>
        </table>
        """

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        parser.scraper.get.return_value = mock_response

        round_data = parser._parse_round("99024", 1)

        assert round_data is not None
        assert len(round_data.pairings) == 1  # Only one pairing (bye)
        assert round_data.pairings[0].player == "Player One"
        assert round_data.pairings[0].opponent is None  # Bye

    def test_parse_round_network_error(self, parser):
        """Test handling network errors when parsing round."""
        parser.scraper.get.side_effect = Exception("Network error")

        round_data = parser._parse_round("99024", 1)

        assert round_data is None

    def test_parse_round_no_table(self, parser):
        """Test parsing round when no matchList table exists."""
        html = "<div>No table</div>"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_response.raise_for_status = Mock()
        parser.scraper.get.return_value = mock_response

        round_data = parser._parse_round("99024", 1)

        assert round_data is None

    def test_parse_tournament_integration(self, parser):
        """Integration test for complete tournament parsing."""
        main_html = """
        <html>
            <span id="numberOfRounds">Rounds 2</span>
        </html>
        """

        round1_html = """
        <table id="matchList">
            <tbody>
                <tr>
                    <td>1</td>
                    <td>Player One (3 Points)</td>
                    <td>Player Two (0 Points)</td>
                </tr>
            </tbody>
        </table>
        """

        round2_html = """
        <table id="matchList">
            <tbody>
                <tr>
                    <td>1</td>
                    <td>Player Two (3 Points)</td>
                    <td>Player One (3 Points)</td>
                </tr>
            </tbody>
        </table>
        """

        # Mock responses
        def mock_get(url, timeout=30):
            response = Mock()
            response.status_code = 200
            response.raise_for_status = Mock()

            if "RoundTourney/99024" in url and "?" not in url:
                response.text = main_html
            elif "p=1" in url:
                response.text = round1_html
            elif "p=2" in url:
                response.text = round2_html
            else:
                response.text = ""

            return response

        parser.scraper.get.side_effect = mock_get

        # Parse tournament
        url = "https://aetherhub.com/Tourney/RoundTourney/99024"
        tournament = parser.parse_tournament(url)

        # Verify structure
        assert isinstance(tournament, AetherhubTournamentData)
        assert tournament.url == url
        assert len(tournament.players) == 2
        assert tournament.players == ["Player One", "Player Two"]
        assert len(tournament.rounds) == 2

        # Verify round 1
        assert tournament.rounds[0].number == 1
        assert len(tournament.rounds[0].pairings) == 2

        # Verify round 2
        assert tournament.rounds[1].number == 2
        assert len(tournament.rounds[1].pairings) == 2
