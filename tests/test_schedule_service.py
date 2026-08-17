"""Тесты ScheduleService и ScheduleHandler — расписание клубов в БД (issue #124/#125)."""

import pytest

from bot.handlers.schedule import SCHEDULE_ROW_NOT_FOUND, ScheduleHandler
from bot.keyboards import CB_SCHEDULE_ROW, CB_SCHEDULE_TOGGLE, Keyboards
from bot.messages import NOT_ADMIN
from core.models import ClubScheduleRow
from services.schedule import WEEKDAYS, ScheduleService, format_import_times, parse_import_times
from services.user import UserService

ADMIN_TG_ID = 7777


@pytest.fixture
def sched_svc(db):
    return ScheduleService(db)


@pytest.fixture
def admin_user(db):
    user_svc = UserService(db)
    u = user_svc.get_or_create(tg_id=ADMIN_TG_ID, username="boss")
    u.is_admin = True
    db.commit()
    return u


@pytest.fixture
def handler(db):
    return ScheduleHandler(ScheduleService(db), UserService(db), Keyboards())


def _row(db, club="Goldfish", weekday="friday", enabled=True, imports="20:00,20:30"):
    row = ClubScheduleRow(
        club_name=club,
        weekday=weekday,
        enabled=enabled,
        create_time="12:00",
        game_time="19:45",
        reminder_time="19:40",
        import_times=imports,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ── CSV времён импорта ───────────────────────────────────────────────────────


class TestImportTimesCsv:
    def test_roundtrip(self):
        times = ["20:00", "20:30", "21:00"]
        assert parse_import_times(format_import_times(times)) == times

    def test_empty_and_none(self):
        assert parse_import_times("") == []
        assert parse_import_times(None) == []

    def test_strips_and_drops_blanks(self):
        assert parse_import_times(" 20:00 , ,20:30, ") == ["20:00", "20:30"]


# ── ensure_defaults ──────────────────────────────────────────────────────────


class TestEnsureDefaults:
    def test_seeds_empty_table(self, sched_svc):
        created = sched_svc.ensure_defaults()
        assert created > 0
        rows = sched_svc.list_rows()
        assert {(r.club_name, r.weekday) for r in rows} == {
            ("Goldfish", "friday"),
            ("Edinorog", "monday"),
            ("Edinorog", "thursday"),
            ("Pair of dice", "tuesday"),
            ("Pair of dice", "sunday"),
            ("Hobby Games", "saturday"),
        }
        assert all(r.enabled for r in rows)

    def test_is_idempotent(self, sched_svc):
        sched_svc.ensure_defaults()
        assert sched_svc.ensure_defaults() == 0
        assert len(sched_svc.list_rows()) == 6

    def test_does_not_resurrect_deleted_rows(self, sched_svc, db):
        sched_svc.ensure_defaults()
        row = sched_svc.list_rows()[0]
        db.delete(row)
        db.commit()
        # таблица не пуста → сид не трогает её, удалённая строка не воскресает
        assert sched_svc.ensure_defaults() == 0
        assert len(sched_svc.list_rows()) == 5


# ── list_rows / toggle ───────────────────────────────────────────────────────


class TestRows:
    def test_list_sorted_by_club_then_weekday(self, sched_svc, db):
        _row(db, club="Edinorog", weekday="thursday")
        _row(db, club="Edinorog", weekday="monday")
        _row(db, club="Goldfish", weekday="friday")
        _row(db, club="Pair of dice", weekday="sunday")
        _row(db, club="Pair of dice", weekday="tuesday")
        _row(db, club="Hobby Games", weekday="saturday")
        assert [(r.club_name, r.weekday) for r in sched_svc.list_rows()] == [
            ("Goldfish", "friday"),
            ("Edinorog", "monday"),
            ("Edinorog", "thursday"),
            ("Pair of dice", "tuesday"),
            ("Pair of dice", "sunday"),
            ("Hobby Games", "saturday"),
        ]

    def test_toggle_flips_and_returns_new_state(self, sched_svc, db):
        row = _row(db)
        assert sched_svc.toggle_enabled(row.id) is False
        assert sched_svc.toggle_enabled(row.id) is True

    def test_toggle_missing_row_returns_none(self, sched_svc):
        assert sched_svc.toggle_enabled(99999) is None


# ── build_clubs: выключенные строки не доходят до планировщика ───────────────


class TestBuildClubs:
    def test_disabled_row_is_not_scheduled(self, sched_svc, db):
        _row(db, club="Goldfish", weekday="friday", enabled=True)
        _row(db, club="Edinorog", weekday="monday", enabled=False)
        clubs = {c.name: c for c in sched_svc.build_clubs()}
        assert [s.weekday for s in clubs["Goldfish"].schedules] == ["friday"]
        assert clubs["Edinorog"].schedules == []

    def test_times_and_imports_pass_through(self, sched_svc, db):
        _row(db, club="Goldfish", weekday="friday", imports="20:00,21:00")
        club = next(c for c in sched_svc.build_clubs() if c.name == "Goldfish")
        sched = club.schedules[0]
        assert sched.create_time == "12:00"
        assert sched.game_time == "19:45"
        assert sched.reminder_time == "19:40"
        assert sched.aetherhub_fetch_times == ["20:00", "21:00"]

    def test_create_days_before_passes_through(self, sched_svc, db):
        row = _row(db, club="Pair of dice", weekday="tuesday")
        row.create_days_before = 1
        db.commit()

        club = next(c for c in sched_svc.build_clubs() if c.name == "Pair of dice")

        assert club.schedules[0].create_days_before == 1

    def test_club_identity_comes_from_code(self, sched_svc, db):
        _row(db, club="Goldfish", weekday="friday")
        club = next(c for c in sched_svc.build_clubs() if c.name == "Goldfish")
        assert club.title_prefix == "🐠 "
        assert club.aetherhub_url

    def test_pair_of_dice_identity_comes_from_code(self, sched_svc, db):
        _row(db, club="Pair of dice", weekday="tuesday")
        club = next(c for c in sched_svc.build_clubs() if c.name == "Pair of dice")
        assert club.title_prefix == "🎲🎲 "
        assert club.aetherhub_url == "https://aetherhub.com/User/Andysays"

    def test_hobby_games_identity_comes_from_code(self, sched_svc, db):
        _row(db, club="Hobby Games", weekday="saturday")
        club = next(c for c in sched_svc.build_clubs() if c.name == "Hobby Games")
        assert club.chat_id == -1002787710855
        assert club.aetherhub_url is None
        assert club.timezone == "Europe/Kaliningrad"


# ── ScheduleHandler ──────────────────────────────────────────────────────────


class TestScheduleHandler:
    def test_non_admin_list_denied(self, handler, db):
        _row(db)
        result = handler.handle_schedule_list(tg_id=1)
        assert NOT_ADMIN in result.text
        assert result.keyboard is None

    def test_list_has_button_per_row(self, handler, admin_user, db):
        r1 = _row(db, club="Goldfish", weekday="friday")
        r2 = _row(db, club="Edinorog", weekday="monday")
        result = handler.handle_schedule_list(ADMIN_TG_ID)
        buttons = [b for row in result.keyboard.inline_keyboard for b in row]
        assert {b.callback_data for b in buttons} == {
            f"{CB_SCHEDULE_ROW}:{r1.id}",
            f"{CB_SCHEDULE_ROW}:{r2.id}",
        }

    def test_list_shows_disabled_rows_too(self, handler, admin_user, db):
        _row(db, club="Goldfish", weekday="friday", enabled=False)
        result = handler.handle_schedule_list(ADMIN_TG_ID)
        assert "выключено" in result.text
        assert len(result.keyboard.inline_keyboard) == 1

    def test_list_and_card_show_previous_day_creation(self, handler, admin_user, db):
        row = _row(db, club="Pair of dice", weekday="tuesday")
        row.create_time = "18:30"
        row.create_days_before = 1
        db.commit()

        schedule = handler.handle_schedule_list(ADMIN_TG_ID)
        card = handler.handle_schedule_row(ADMIN_TG_ID, row.id)

        assert "создание накануне 18:30" in schedule.text
        assert "Создание турнира: накануне в 18:30" in card.text

    def test_empty_schedule_has_no_keyboard(self, handler, admin_user):
        result = handler.handle_schedule_list(ADMIN_TG_ID)
        assert result.keyboard is None

    def test_row_card_shows_times(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_schedule_row(ADMIN_TG_ID, row.id)
        assert "12:00" in result.text
        assert "19:45" in result.text
        assert "20:00" in result.text

    def test_row_card_missing_row_alerts(self, handler, admin_user):
        result = handler.handle_schedule_row(ADMIN_TG_ID, 99999)
        assert result.is_alert
        assert result.text == SCHEDULE_ROW_NOT_FOUND

    def test_toggle_updates_card_and_button(self, handler, admin_user, db):
        row = _row(db, enabled=True)
        result = handler.handle_toggle_row(ADMIN_TG_ID, row.id)
        assert "выключено" in result.text
        toggle = next(
            b for r in result.keyboard.inline_keyboard for b in r if b.callback_data == f"{CB_SCHEDULE_TOGGLE}:{row.id}"
        )
        assert "Включить" in toggle.text  # выключено → предлагаем включить

    def test_toggle_non_admin_denied(self, handler, db):
        row = _row(db, enabled=True)
        result = handler.handle_toggle_row(tg_id=1, row_id=row.id)
        assert result.is_alert
        assert NOT_ADMIN in result.text
        assert ScheduleService(handler.schedule_svc.db).get_row(row.id).enabled is True


# ══════════════════════ Фаза 2: редактирование времён и дня недели ══════════════

from bot.handlers.schedule import (  # noqa: E402
    BAD_IMPORTS,
    BAD_TIME,
    WEEKDAY_TAKEN,
    _parse_imports_preset,
    imports_summary,
)
from services.schedule import generate_import_times, normalize_time  # noqa: E402


class TestNormalizeTime:
    def test_valid(self):
        assert normalize_time("9:05") == "09:05"
        assert normalize_time("19:30") == "19:30"
        assert normalize_time(" 00:00 ") == "00:00"

    def test_invalid(self):
        assert normalize_time("25:00") is None
        assert normalize_time("12:60") is None
        assert normalize_time("лол") is None
        assert normalize_time("1230") is None


class TestGenerateImportTimes:
    def test_crosses_midnight(self):
        assert generate_import_times("20:00", "00:30", 30) == [
            "20:00",
            "20:30",
            "21:00",
            "21:30",
            "22:00",
            "22:30",
            "23:00",
            "23:30",
            "00:00",
            "00:30",
        ]

    def test_simple_window(self):
        assert generate_import_times("12:00", "13:00", 30) == ["12:00", "12:30", "13:00"]

    def test_rejects_tiny_step(self):
        assert generate_import_times("12:00", "13:00", 1) is None

    def test_rejects_window_over_day(self):
        # end == start трактуется как +сутки → ровно 24ч, это ещё ок; строго больше — нет
        assert generate_import_times("12:00", "12:00", 60) is not None


class TestImportsSummary:
    def test_range(self):
        assert imports_summary(["20:00", "20:30", "21:00"]) == "20:00–21:00 (3)"

    def test_single(self):
        assert imports_summary(["12:30"]) == "12:30"

    def test_empty(self):
        assert imports_summary([]) == "выключены"


class TestParseImportsPreset:
    def test_valid(self):
        assert _parse_imports_preset("20:00-00:30/30")[0] == "20:00"
        assert len(_parse_imports_preset("20:00-00:30/30")) == 10

    def test_spaces_tolerated(self):
        assert _parse_imports_preset(" 12:00 - 13:00 / 30 ") == ["12:00", "12:30", "13:00"]

    def test_bad_formats(self):
        assert _parse_imports_preset("лол") is None
        assert _parse_imports_preset("20:00/30") is None
        assert _parse_imports_preset("20:00-00:30") is None
        assert _parse_imports_preset("25:00-00:30/30") is None


class TestSetTimeFields:
    def test_set_create_and_game(self, sched_svc, db):
        row = _row(db)
        assert sched_svc.set_time_field(row.id, "create", "09:00") is True
        assert sched_svc.set_time_field(row.id, "game", "18:15") is True
        r = sched_svc.get_row(row.id)
        assert r.create_time == "09:00"
        assert r.game_time == "18:15"

    def test_set_reminder_and_disable(self, sched_svc, db):
        row = _row(db)
        sched_svc.set_reminder(row.id, "19:00")
        assert sched_svc.get_row(row.id).reminder_time == "19:00"
        sched_svc.set_reminder(row.id, None)
        assert sched_svc.get_row(row.id).reminder_time is None

    def test_set_import_times(self, sched_svc, db):
        row = _row(db)
        sched_svc.set_import_times(row.id, ["20:00", "21:00"])
        assert sched_svc.get_row(row.id).import_times == "20:00,21:00"
        sched_svc.set_import_times(row.id, [])
        assert sched_svc.get_row(row.id).import_times == ""

    def test_setters_missing_row(self, sched_svc):
        assert sched_svc.set_time_field(999, "create", "10:00") is False
        assert sched_svc.set_reminder(999, None) is False
        assert sched_svc.set_import_times(999, []) is False


class TestSetWeekday:
    def test_changes_weekday(self, sched_svc, db):
        row = _row(db, club="Goldfish", weekday="friday")
        assert sched_svc.set_weekday(row.id, "saturday") == "ok"
        assert sched_svc.get_row(row.id).weekday == "saturday"

    def test_same_weekday_is_ok_noop(self, sched_svc, db):
        row = _row(db, weekday="friday")
        assert sched_svc.set_weekday(row.id, "friday") == "ok"

    def test_duplicate_rejected(self, sched_svc, db):
        _row(db, club="Edinorog", weekday="monday")
        thu = _row(db, club="Edinorog", weekday="thursday")
        assert sched_svc.set_weekday(thu.id, "monday") == "duplicate"
        assert sched_svc.get_row(thu.id).weekday == "thursday"

    def test_same_weekday_other_club_ok(self, sched_svc, db):
        _row(db, club="Goldfish", weekday="monday")
        edi = _row(db, club="Edinorog", weekday="thursday")
        assert sched_svc.set_weekday(edi.id, "monday") == "ok"

    def test_missing_row(self, sched_svc):
        assert sched_svc.set_weekday(999, "monday") == "not_found"


class TestHandlerEdit:
    def test_edit_field_prompt_admin(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_edit_field_prompt(ADMIN_TG_ID, row.id, "create")
        assert not result.is_alert
        assert "ЧЧ:ММ" in result.text

    def test_edit_field_prompt_non_admin(self, handler, db):
        row = _row(db)
        result = handler.handle_edit_field_prompt(tg_id=1, row_id=row.id, field="create")
        assert result.is_alert
        assert NOT_ADMIN in result.text

    def test_set_time_valid_updates_card(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_set_time(ADMIN_TG_ID, row.id, "create", "09:15")
        assert result.keyboard is not None
        assert "09:15" in result.text

    def test_set_time_bad_format_no_change(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_set_time(ADMIN_TG_ID, row.id, "create", "лол")
        assert result.keyboard is None
        assert result.text == BAD_TIME
        assert ScheduleService(handler.schedule_svc.db).get_row(row.id).create_time == "12:00"

    def test_set_reminder_disable_word(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_set_time(ADMIN_TG_ID, row.id, "reminder", "выкл")
        assert result.keyboard is not None
        assert ScheduleService(handler.schedule_svc.db).get_row(row.id).reminder_time is None

    def test_set_imports_preset(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_set_imports(ADMIN_TG_ID, row.id, "20:00-00:30/30")
        assert result.keyboard is not None
        assert ScheduleService(handler.schedule_svc.db).get_row(row.id).import_times.startswith("20:00,20:30")

    def test_set_imports_disable(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_set_imports(ADMIN_TG_ID, row.id, "выкл")
        assert result.keyboard is not None
        assert ScheduleService(handler.schedule_svc.db).get_row(row.id).import_times == ""

    def test_set_imports_bad(self, handler, admin_user, db):
        row = _row(db)
        result = handler.handle_set_imports(ADMIN_TG_ID, row.id, "ерунда")
        assert result.keyboard is None
        assert result.text == BAD_IMPORTS

    def test_weekday_picker_marks_current(self, handler, admin_user, db):
        row = _row(db, weekday="friday")
        result = handler.handle_weekday_picker(ADMIN_TG_ID, row.id)
        labels = [b.text for r in result.keyboard.inline_keyboard for b in r]
        assert any(t.startswith("✅") and "пятниц" in t for t in labels)

    def test_set_weekday_applies(self, handler, admin_user, db):
        row = _row(db, club="Goldfish", weekday="friday")
        sat_idx = WEEKDAYS.index("saturday")
        result = handler.handle_set_weekday(ADMIN_TG_ID, row.id, sat_idx)
        assert result.keyboard is not None
        assert ScheduleService(handler.schedule_svc.db).get_row(row.id).weekday == "saturday"

    def test_set_weekday_duplicate_alerts(self, handler, admin_user, db):
        _row(db, club="Edinorog", weekday="monday")
        thu = _row(db, club="Edinorog", weekday="thursday")
        mon_idx = WEEKDAYS.index("monday")
        result = handler.handle_set_weekday(ADMIN_TG_ID, thu.id, mon_idx)
        assert result.is_alert
        assert result.text == WEEKDAY_TAKEN
