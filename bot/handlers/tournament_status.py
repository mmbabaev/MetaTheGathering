"""Resolve the latest round's pairings to participants for the 'status by pairings' view.

A per-user setting (``status_by_pairings``) makes the admin participant keyboard lay
players out by table (two buttons per row) instead of a single column. This module
only does the data resolution; the keyboard layout lives in ``bot/keyboards``.
"""

from __future__ import annotations

from core import models
from services.aetherhub_import_service import AetherhubImportService


def pairing_rows(db, tournament_id: int, participants: list):
    """Resolve the latest round's pairings to participants.

    Returns ``(pairs, unpaired)`` or ``None`` if there are no pairings yet (caller
    falls back to the flat keyboard). ``pairs`` = ``(table, p1, name1, p2, name2)``;
    ``p1``/``p2`` are Participants (or None if a paired name isn't a registered
    participant), ``name2`` is None for a bye.
    """
    imp = AetherhubImportService(db)
    rounds = imp.get_round_numbers(tournament_id)
    if not rounds:
        return None
    pairings = imp.get_pairings(tournament_id, max(rounds))
    if not pairings:
        return None

    part_by_uid = {p.user_id: p for p in participants}
    names = {p.player_name for p in pairings} | {p.opponent_name for p in pairings if p.opponent_name}
    name_to_part: dict[str, models.Participant | None] = {}
    for name in names:
        user = imp.find_user_by_name(name)
        name_to_part[name] = part_by_uid.get(user.id) if user else None

    pairs = []
    seen: set = set()
    paired_uids: set = set()
    ordered = sorted(pairings, key=lambda x: (x.table_number if x.table_number is not None else 10**9, x.player_name))
    for pg in ordered:
        key = frozenset((pg.player_name, pg.opponent_name)) if pg.opponent_name else ("bye", pg.player_name)
        if key in seen:
            continue
        seen.add(key)
        p1 = name_to_part.get(pg.player_name)
        p2 = name_to_part.get(pg.opponent_name) if pg.opponent_name else None
        pairs.append((pg.table_number, p1, pg.player_name, p2, pg.opponent_name))
        for p in (p1, p2):
            if p is not None:
                paired_uids.add(p.user_id)

    unpaired = [p for p in participants if p.user_id not in paired_uids]
    return pairs, unpaired
