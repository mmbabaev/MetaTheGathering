from config import AppConfig

app_config = AppConfig(
    debug=False,
    tournament_timezone="Europe/Moscow",
    tournament_create_time="19:20",
    goldfish_chat_id=-1001399656692,  # @MoscowPauperChat
    edinorog_chat_id=-1001631119846,  # @paupermoscow «Паупер в Единороге»
    owner_chat_id=232778570,  # mbabaev (владелец) — пока все служебные анонсы шлём ему в личку
)
