"""Слияние дублей игроков (User) — поиск кандидатов и безопасный merge.

Переиспользует ``UserService.merge_users_by_id`` (поля участий сливаются при
конфликте, см. сервис). По умолчанию merge — DRY-RUN: показывает план и НЕ пишет;
выполнение только с ``--yes``.

Цель (--target) должна быть РЕАЛЬНЫМ аккаунтом (tg_id > 0); source'ы (--source) —
обычно плейсхолдеры. Запускать с нужной базой, напр. на сервере:
    BOT_ENV=prod python3 scripts/merge_players.py find "Бурбаев"
    BOT_ENV=prod python3 scripts/merge_players.py merge --target 269 --source 360 285 \
        --last Бурбаев --first Константин --yes
"""

import argparse
import sys

from core import models
from core.database import SessionLocal
from services.user import UserService


def _describe(db, uid: int) -> str:
    u = db.get(models.User, uid)
    if not u:
        return f"id={uid}: НЕ НАЙДЕН"
    parts = db.query(models.Participant).filter_by(user_id=uid).order_by(models.Participant.tournament_id).all()
    lines = [
        f"id={uid} tg={u.tg_id} @{u.username or '-'} '{u.last_name or ''} {u.first_name or ''}' участий={len(parts)}"
    ]
    for p in parts:
        a = db.get(models.Archetype, p.archetype_id) if p.archetype_id else None
        lines.append(f"    t#{p.tournament_id} arch={a.name if a else '—'} place={p.final_place}")
    return "\n".join(lines)


def cmd_find(args) -> None:
    db = SessionLocal()
    q = f"%{args.query.lower()}%"
    users = (
        db.query(models.User)
        .filter(models.User.first_name.ilike(q) | models.User.last_name.ilike(q))
        .order_by(models.User.id)
        .all()
    )
    print(f"Найдено: {len(users)}")
    for u in users:
        print(_describe(db, u.id))


def cmd_merge(args) -> None:
    db = SessionLocal()
    user_svc = UserService(db)

    if not db.get(models.User, args.target):
        sys.exit(f"target id={args.target} не найден")
    print("=== ЦЕЛЬ (остаётся) ===")
    print(_describe(db, args.target))
    print("\n=== ИСТОЧНИКИ (будут удалены, данные перенесены) ===")
    for s in args.source:
        print(_describe(db, s))

    if not args.yes:
        print("\n[DRY-RUN] ничего не записано. Добавь --yes для выполнения.")
        return

    for s in args.source:
        ok = user_svc.merge_users_by_id(s, args.target, adopt_name=False)
        print(f"merge {s} -> {args.target}: {'ok' if ok else 'ПРОПУЩЕН (не найден / совпадает)'}")
    if args.last or args.first:
        tgt = db.get(models.User, args.target)
        if args.last is not None:
            tgt.last_name = args.last
        if args.first is not None:
            tgt.first_name = args.first
        db.commit()

    print("\n=== ИТОГ ===")
    print(_describe(db, args.target))


def main() -> None:
    parser = argparse.ArgumentParser(description="Слияние дублей игроков")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_find = sub.add_parser("find", help="найти пользователей по части имени/фамилии")
    p_find.add_argument("query")
    p_find.set_defaults(func=cmd_find)

    p_merge = sub.add_parser("merge", help="слить source'ы в target (dry-run без --yes)")
    p_merge.add_argument("--target", type=int, required=True, help="id записи, которая остаётся (реальный аккаунт)")
    p_merge.add_argument("--source", type=int, nargs="+", required=True, help="id записей-дублей для слияния")
    p_merge.add_argument("--last", help="проставить фамилию итоговой записи")
    p_merge.add_argument("--first", help="проставить имя итоговой записи")
    p_merge.add_argument("--yes", action="store_true", help="выполнить (без флага — только показать план)")
    p_merge.set_defaults(func=cmd_merge)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
