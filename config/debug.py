from config import AppConfig

app_config = AppConfig(
    debug=True,
    tournament_timezone="Europe/Moscow",
    tournament_create_time="14:20",
    notify_allowed_ids=[232778570, 7776168515, 8749662186],  # mbabaev, mmbabaev, mmbabaev2
    goldfish_chat_id=-1003631429183,
    edinorog_chat_id=-1003631429183,
    pair_of_dice_chat_id=None,  # никогда не использовать production-чат Pair of dice в debug
    hobby_games_chat_id=None,  # никогда не использовать production-чат Hobby Games в debug
    owner_chat_id=232778570,  # mbabaev (владелец) — служебные анонсы в личку
)
