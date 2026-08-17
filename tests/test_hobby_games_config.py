from config.debug import app_config as debug_config
from config.prod import app_config as prod_config
from core.clubs import club_identities, default_clubs, default_schedules


def test_hobby_games_identity():
    identity = next(row for row in club_identities() if row.name == "Hobby Games")

    assert identity.chat_id == -1002787710855
    assert identity.aetherhub_url is None
    assert identity.title_prefix == "🎲 "
    assert identity.magicoculus_city == "Калининград"
    assert identity.timezone == "Europe/Kaliningrad"


def test_hobby_games_production_and_debug_chat_ids_are_separate():
    assert prod_config.hobby_games_chat_id == -1002787710855
    assert debug_config.hobby_games_chat_id is None


def test_hobby_games_defaults_follow_pair_of_dice_registration_flow():
    schedule = next(row for row in default_schedules() if row.club_name == "Hobby Games")

    assert schedule.weekday == "saturday"
    assert schedule.create_time == "18:30"
    assert schedule.create_days_before == 1
    assert schedule.game_time == "17:00"
    assert schedule.reminder_time == "16:55"
    assert schedule.import_times == []


def test_hobby_games_default_club_uses_local_timezone():
    club = next(row for row in default_clubs() if row.name == "Hobby Games")

    assert club.timezone == "Europe/Kaliningrad"
    assert [schedule.weekday for schedule in club.schedules] == ["saturday"]
