"""Owner Board Lab fixture pool used before real stats providers are connected."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from services.achievements.bingo.models import (
    AchievementTypeManifest,
    Category,
    DataSource,
    Difficulty,
    EligibilityResult,
    InstantiatedCandidate,
    ManifestStatus,
    Requirement,
)
from services.achievements.bingo.parameterizers import (
    PLAY_DECK_CODE,
    FrozenDeckTarget,
    instantiate_play_deck_candidates,
)

FIXTURE_CATALOG_VERSION = "board-lab-fixtures-v4"
FIXTURE_DECK_STATS_SNAPSHOT_ID = "fixture-stats-2026-08-19-365d"


class FixturePersona(str, Enum):
    NEWCOMER = "newcomer"
    AMATEUR = "amateur"
    REGULAR = "regular"
    PRO = "pro"


@dataclass(frozen=True)
class _PersonaFacts:
    label: str
    history_matches: int
    known_decks: int
    known_clubs: int
    has_h2h_baseline: bool


PERSONA_FACTS: dict[FixturePersona, _PersonaFacts] = {
    FixturePersona.NEWCOMER: _PersonaFacts("Новичок", 4, 1, 1, False),
    FixturePersona.AMATEUR: _PersonaFacts("Любитель", 28, 3, 1, True),
    FixturePersona.REGULAR: _PersonaFacts("Регуляр", 96, 2, 2, True),
    FixturePersona.PRO: _PersonaFacts("Про", 160, 6, 2, True),
}


_BASIC = (
    Requirement.SELF_REGISTERED,
    Requirement.ACTUALLY_PLAYED,
    Requirement.TOURNAMENT_CLOSED,
    Requirement.RESULT_COMPLETE,
)
_DECK = (*_BASIC, Requirement.PLAYER_DECK_KNOWN)
_H2H = (*_BASIC, Requirement.OPPONENT_IDENTIFIED, Requirement.STATS_BASELINE)
_MATCHUP = (*_H2H, Requirement.PLAYER_DECK_KNOWN, Requirement.OPPONENT_DECK_KNOWN)

FIXTURE_DECK_TARGETS: tuple[FrozenDeckTarget, ...] = (
    FrozenDeckTarget("Blue Terror", "Хитрый уж", rank=1, participations=46, players=27),
    FrozenDeckTarget("Grixis Affinity", "Родство с металлом", rank=2, participations=36, players=20),
    FrozenDeckTarget("Jund Midrange", "Мосты не горят", rank=3, participations=29, players=15),
    FrozenDeckTarget("Red Rally", "И грянул рог", rank=4, participations=28, players=10),
    FrozenDeckTarget("Spy Walls", "У стен есть глаза", rank=5, participations=25, players=7),
    FrozenDeckTarget("Red Madness", "Вспыльчивый нрав", rank=6, participations=23, players=17),
    FrozenDeckTarget("BG Gardens", "Цветы зла", rank=7, participations=22, players=9),
    FrozenDeckTarget("White Aggro", "Следствие ведут двое", rank=8, participations=22, players=17),
    FrozenDeckTarget("Flicker Tron", "Стена всё помнит", rank=9, participations=20, players=6),
    FrozenDeckTarget("Bogles", "Броня крепка", rank=10, participations=19, players=10),
)


def _manifest(
    code: str,
    title: str,
    hint: str,
    category: Category,
    difficulty: Difficulty,
    *,
    source: DataSource = DataSource.DATABASE,
    requirements: tuple[Requirement, ...] = _BASIC,
    fallback_codes: tuple[str, ...] = (),
    incompatibilities: tuple[str, ...] = (),
    evidence_fields: tuple[str, ...] | None = None,
    parameterizer_key: str | None = None,
    progress_evaluator_key: str | None = None,
    completion_evaluator_key: str | None = None,
) -> AchievementTypeManifest:
    if evidence_fields is None:
        evidence_fields = {
            DataSource.DATABASE: ("tournament_id",),
            DataSource.STATS_SNAPSHOT: ("stats_snapshot_id", "tournament_id"),
            DataSource.PEER_CONFIRMATION: (
                "tournament_id",
                "round_number",
                "opponent_user_id",
                "confirmation_id",
            ),
        }[source]
    return AchievementTypeManifest(
        code=code,
        title_template=title,
        hint_template=hint,
        category=category,
        difficulty=difficulty,
        data_source=source,
        requirements=requirements,
        mechanic_key=code,
        parameterizer_key=parameterizer_key or f"{code}_fixture_v1",
        progress_evaluator_key=progress_evaluator_key or f"{code}_preview_progress_v1",
        completion_evaluator_key=completion_evaluator_key or f"{code}_preview_completion_v1",
        evidence_fields=evidence_fields,
        fallback_codes=fallback_codes,
        incompatibilities=incompatibilities,
        status=ManifestStatus.READY_FOR_PREVIEW,
    )


PREVIEW_MANIFESTS: tuple[AchievementTypeManifest, ...] = (
    # Easy: low-winrate routes and self-registration incentives.
    _manifest(
        "self_register",
        "Сам себе метаписец",
        "Сам запиши свою колоду на турнир",
        Category.PARTICIPATION,
        Difficulty.EASY,
    ),
    _manifest(
        "play_tournament",
        "Выйти на старт",
        "Фактически сыграй турнир после активации поля",
        Category.PARTICIPATION,
        Difficulty.EASY,
    ),
    _manifest(
        "try_new_deck",
        "Новая глава",
        "Сыграй незнакомым тебе архетипом",
        Category.DECK,
        Difficulty.EASY,
        requirements=_DECK,
    ),
    _manifest(
        "record_opponent_deck", "Полевые заметки", "Запиши колоду реального оппонента", Category.SOCIAL, Difficulty.EASY
    ),
    _manifest(
        "visit_second_club", "Смена декораций", "Сыграй турнир в другом клубе", Category.EXPLORATION, Difficulty.EASY
    ),
    _manifest(
        "finish_all_rounds",
        "Полная дистанция",
        "Сыграй все раунды турнира без drop",
        Category.PARTICIPATION,
        Difficulty.EASY,
    ),
    _manifest(
        PLAY_DECK_CODE,
        "{flavor_title}",
        "Сыграй турнир на колоде {deck_general_name}",
        Category.DECK,
        Difficulty.EASY,
        source=DataSource.STATS_SNAPSHOT,
        requirements=_DECK,
        fallback_codes=("try_new_deck",),
        evidence_fields=("stats_snapshot_id", "tournament_id", "deck_general_name"),
        parameterizer_key="play_deck_from_frozen_catalog_v1",
        progress_evaluator_key="play_deck_binary_progress_v1",
        completion_evaluator_key="play_deck_completed_v1",
    ),
    # Medium: recognizable tournament stories without elite baseline requirements.
    _manifest(
        "comeback", "Камбэк", "Проиграй первый раунд и выиграй оставшиеся", Category.PERFORMANCE, Difficulty.MEDIUM
    ),
    _manifest("tourist", "Гастролёр", "Сыграй турниры в двух разных клубах", Category.EXPLORATION, Difficulty.MEDIUM),
    _manifest(
        "battle_kit",
        "Боевой набор",
        "Сделай X-0 двумя разными колодами",
        Category.DECK,
        Difficulty.MEDIUM,
        requirements=_DECK,
    ),
    _manifest(
        "scribe_event",
        "Летописец турнира",
        "Запиши колоды трём разным игрокам за турнир",
        Category.SOCIAL,
        Difficulty.MEDIUM,
    ),
    _manifest(
        "finisher",
        "Финишер",
        "Выиграй последний раунд и закончи турнир в плюсе",
        Category.PERFORMANCE,
        Difficulty.MEDIUM,
    ),
    _manifest(
        "stable_form",
        "Стабильная форма",
        "Закончи в плюсе три сыгранных турнира подряд",
        Category.PERFORMANCE,
        Difficulty.MEDIUM,
    ),
    _manifest(
        "heretic",
        "Еретик",
        "Закончи в плюсе на колоде вне frozen top-10",
        Category.DECK,
        Difficulty.MEDIUM,
        source=DataSource.STATS_SNAPSHOT,
        requirements=_DECK,
    ),
    _manifest(
        "last_train",
        "Последний вагон",
        "Запиши колоду последним и сделай X-0",
        Category.PARTICIPATION,
        Difficulty.MEDIUM,
    ),
    _manifest(
        "loyal_sight",
        "Верный прицел",
        "Сделай X-0 одной колодой несколько раз",
        Category.DECK,
        Difficulty.MEDIUM,
        requirements=_DECK,
    ),
    _manifest(
        "mirror", "Зеркало", "Выиграй матч одинаковых архетипов", Category.H2H, Difficulty.MEDIUM, requirements=_MATCHUP
    ),
    # Hard: some stats-heavy candidates have explicit database fallbacks.
    _manifest(
        "clean_sweep", "Сухая победа", "Выиграй все сыгранные матчи турнира 2-0", Category.PERFORMANCE, Difficulty.HARD
    ),
    _manifest(
        "sweet_revenge",
        "Сладкая месть",
        "Победи одного из замороженных неудобных соперников",
        Category.H2H,
        Difficulty.HARD,
        source=DataSource.STATS_SNAPSHOT,
        requirements=_H2H,
        fallback_codes=("clean_sweep",),
    ),
    _manifest(
        "winrate_growth",
        "На подъёме",
        "Подними винрейт на 5 п.п. между равными окнами",
        Category.PERFORMANCE,
        Difficulty.HARD,
        source=DataSource.STATS_SNAPSHOT,
        requirements=(*_BASIC, Requirement.STATS_BASELINE),
        fallback_codes=("club_conqueror",),
    ),
    _manifest(
        "giant_slayer",
        "Гигантоубийца",
        "Победи игрока из frozen top-10",
        Category.H2H,
        Difficulty.HARD,
        source=DataSource.STATS_SNAPSHOT,
        requirements=(*_BASIC, Requirement.OPPONENT_IDENTIFIED),
    ),
    _manifest(
        "skull_collector",
        "Коллекционер скальпов",
        "Победи представителей трёх популярных колод",
        Category.DECK,
        Difficulty.HARD,
        source=DataSource.STATS_SNAPSHOT,
        requirements=_MATCHUP,
    ),
    _manifest(
        "mirror_breaker",
        "Разрушитель зеркал",
        "Выиграй зеркала на трёх разных колодах",
        Category.H2H,
        Difficulty.HARD,
        requirements=_MATCHUP,
    ),
    _manifest(
        "club_conqueror",
        "Клубный завоеватель",
        "Закончи в плюсе одной колодой в двух клубах",
        Category.EXPLORATION,
        Difficulty.HARD,
        requirements=_DECK,
    ),
    _manifest(
        "nemesis",
        "Немезида",
        "Победи соперника после серии личных поражений",
        Category.H2H,
        Difficulty.HARD,
        requirements=_H2H,
        fallback_codes=("sniper",),
    ),
    _manifest(
        "matchup_healed",
        "Матчап вылечен",
        "Улучши результат против худшего матчапа",
        Category.DECK,
        Difficulty.HARD,
        source=DataSource.STATS_SNAPSHOT,
        requirements=_MATCHUP,
        fallback_codes=("sniper",),
    ),
    _manifest(
        "sniper", "Снайпер", "Сделай X-0, проиграв не больше одной партии", Category.PERFORMANCE, Difficulty.HARD
    ),
    # Rare: no more than one per row; peer-confirmed candidates are separately capped.
    _manifest(
        "king_top_table",
        "Король верхнего стола",
        "Выиграй за первым столом в последнем раунде",
        Category.PERFORMANCE,
        Difficulty.RARE,
    ),
    _manifest(
        "marathon",
        "Марафонец",
        "Сыграй все раунды турнира на пять и более раундов",
        Category.PARTICIPATION,
        Difficulty.RARE,
    ),
    _manifest(
        "peer_jackpot",
        "Джекпот",
        "Получи максимальный результат 12 из 12",
        Category.PEER_CONFIRMATION,
        Difficulty.RARE,
        source=DataSource.PEER_CONFIRMATION,
        requirements=(*_BASIC, Requirement.OPPONENT_IDENTIFIED),
    ),
    _manifest(
        "peer_blade",
        "На лезвии ножа",
        "Выиграй партию, оставшись ровно с одной жизнью",
        Category.PEER_CONFIRMATION,
        Difficulty.RARE,
        source=DataSource.PEER_CONFIRMATION,
        requirements=(*_BASIC, Requirement.OPPONENT_IDENTIFIED),
    ),
    _manifest(
        "peer_last_moment",
        "Последний момент",
        "Выиграй в дополнительных ходах",
        Category.PEER_CONFIRMATION,
        Difficulty.RARE,
        source=DataSource.PEER_CONFIRMATION,
        requirements=(*_BASIC, Requirement.OPPONENT_IDENTIFIED),
    ),
    _manifest(
        "peer_topdeck",
        "С верхушки",
        "Выиграй благодаря решающей карте с верха",
        Category.PEER_CONFIRMATION,
        Difficulty.RARE,
        source=DataSource.PEER_CONFIRMATION,
        requirements=(*_BASIC, Requirement.OPPONENT_IDENTIFIED),
    ),
)


def fixture_candidates(persona: FixturePersona) -> tuple[InstantiatedCandidate, ...]:
    """Instantiate the same versioned pool for one of the four fairness personas."""

    facts = PERSONA_FACTS[persona]
    candidates: list[InstantiatedCandidate] = []
    high_winrate_codes = {
        "clean_sweep",
        "sweet_revenge",
        "winrate_growth",
        "giant_slayer",
        "skull_collector",
        "mirror_breaker",
        "nemesis",
        "matchup_healed",
        "sniper",
        "king_top_table",
    }
    peer_index = 0

    for manifest in PREVIEW_MANIFESTS:
        if manifest.code == PLAY_DECK_CODE:
            candidates.extend(
                instantiate_play_deck_candidates(
                    manifest,
                    FIXTURE_DECK_TARGETS,
                    stats_snapshot_id=FIXTURE_DECK_STATS_SNAPSHOT_ID,
                    frozen_context={
                        "persona": persona.value,
                        "historyMatches": facts.history_matches,
                        "knownDecks": facts.known_decks,
                        "knownClubs": facts.known_clubs,
                    },
                )
            )
            continue
        eligible = facts.has_h2h_baseline or Requirement.STATS_BASELINE not in manifest.requirements
        eligibility = (
            EligibilityResult(eligible=True, baseline_sample=facts.history_matches)
            if eligible
            else EligibilityResult(
                eligible=False,
                reason_code="insufficient_h2h_baseline",
                detail=f"{facts.label}: недостаточно истории личных встреч",
                baseline_sample=facts.history_matches,
            )
        )
        target_opponent_id = None
        if manifest.category == Category.H2H:
            target_opponent_id = f"opponent-{manifest.code}"
        elif manifest.data_source == DataSource.PEER_CONFIRMATION:
            peer_index += 1
            target_opponent_id = f"peer-opponent-{peer_index}"

        candidates.append(
            InstantiatedCandidate.from_manifest(
                manifest,
                candidate_id=f"{persona.value}:{manifest.code}:v{manifest.version}",
                title=manifest.title_template,
                hint=manifest.hint_template,
                eligibility=eligibility,
                frozen_params={
                    "persona": persona.value,
                    "historyMatches": facts.history_matches,
                    "knownDecks": facts.known_decks,
                    "knownClubs": facts.known_clubs,
                },
                attainability={
                    Difficulty.EASY: 0.9,
                    Difficulty.MEDIUM: 0.65,
                    Difficulty.HARD: 0.35,
                    Difficulty.RARE: 0.2,
                }[manifest.difficulty],
                requires_high_winrate=manifest.code in high_winrate_codes,
                target_opponent_id=target_opponent_id,
            )
        )
    return tuple(candidates)
