from config import AppConfig

app_config = AppConfig(
    debug=False,
    tournament_timezone="Europe/Moscow",
    tournament_create_time="19:20",
    goldfish_chat_id=-1001399656692,  # @MoscowPauperChat
    edinorog_chat_id=-1001631119846,  # @paupermoscow «Паупер в Единороге»
    pair_of_dice_chat_id=-1001236834154,  # «Питерский паупер» в Pair of dice
    hobby_games_chat_id=-1002787710855,  # Калининград, Hobby Games
    endstep_ru_chat_id=-1003631429183,  # @metathegatheringtestgroup; заменить при переезде Endstep-ru
    owner_chat_id=232778570,  # mbabaev (владелец) — пока все служебные анонсы шлём ему в личку
)
