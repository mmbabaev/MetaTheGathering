from config import AppConfig

app_config = AppConfig(
    debug=True,
    tournament_timezone="Europe/Moscow",
    tournament_create_time="14:20",
    notify_allowed_ids=[232778570, 7776168515],  # mbabaev, mmbabaev
    goldfish_chat_id=-5194706758,
    edinorog_chat_id=-5194706758,
)
