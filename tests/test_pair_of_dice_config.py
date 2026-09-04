from config.debug import app_config as debug_config
from config.prod import app_config as prod_config
from core.clubs import club_identities, default_schedules


def test_pair_of_dice_identity():
    identity = next(row for row in club_identities() if row.name == "Pair of dice")

    assert identity.aetherhub_url == "https://aetherhub.com/User/Andysays"
    assert identity.title_prefix == "🎲🎲 "
    assert identity.magicoculus_city == "Санкт-Петербург"


def test_pair_of_dice_production_and_debug_chat_ids_are_separate():
    assert prod_config.pair_of_dice_chat_id == -1001236834154
    assert debug_config.pair_of_dice_chat_id is None


def test_pair_of_dice_defaults_open_registration_the_evening_before():
    schedules = {(row.club_name, row.weekday): row for row in default_schedules()}
    tuesday = schedules[("Pair of dice", "tuesday")]
    sunday = schedules[("Pair of dice", "sunday")]

    assert tuesday.create_time == "18:30"
    assert tuesday.create_days_before == 1
    assert tuesday.game_time == "19:30"
    assert tuesday.reminder_time == "19:25"
    assert tuesday.import_times[0] == "20:00"
    assert tuesday.import_times[-1] == "00:30"

    assert sunday.create_time == "18:30"
    assert sunday.create_days_before == 1
    assert sunday.game_time == "13:30"
    assert sunday.reminder_time == "13:25"
    assert sunday.import_times[0] == "14:00"
    assert sunday.import_times[-1] == "18:30"
