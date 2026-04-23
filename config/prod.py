from config import AppConfig

app_config = AppConfig(
    debug=False,
    tournament_timezone="Europe/Moscow",
    tournament_create_time="19:20",
    goldfish_chat_id=None,  # TODO: fill in prod chat ID
    edinorog_chat_id=None,  # TODO: fill in prod chat ID
)
