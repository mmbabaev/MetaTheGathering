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


def test_pair_of_dice_defaults_match_edinorog_monday():
    schedules = {(row.club_name, row.weekday): row for row in default_schedules()}
    edinorog = schedules[("Edinorog", "monday")]

    for weekday in ("monday", "wednesday"):
        pair_of_dice = schedules[("Pair of dice", weekday)]
        assert pair_of_dice.create_time == edinorog.create_time
        assert pair_of_dice.game_time == edinorog.game_time
        assert pair_of_dice.reminder_time == edinorog.reminder_time
        assert pair_of_dice.import_times == edinorog.import_times
