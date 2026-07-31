#!/usr/bin/env python3
"""Build JSON import material for migrations that have no exact AetherHub URL."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.tournament_sheet import extract_sheet_tournaments

NO_EXACT_URL_STATUSES = {"missing_aetherhub", "ambiguous_aetherhub", "roster_mismatch"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--migration-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report = json.loads(args.migration_report.read_text())
    target_keys = {
        (item["club"], date.fromisoformat(item["date"]))
        for item in report["items"]
        if item["status"] in NO_EXACT_URL_STATUSES
    }
    tournaments, issues = extract_sheet_tournaments(args.workbook, target_keys)
    payload = {
        "schema_version": 1,
        "source": "google-sheets:1eq-ffPDkyyNpbiQibyg1S303PvSxLq7VcxVcSPJmMhc",
        "tournaments": [row.model_dump(mode="json") for row in tournaments],
        "issues": issues,
        "summary": {
            "requested": len(target_keys),
            "exported": len(tournaments),
            "not_exported": len(target_keys) - len(tournaments),
            "issues": len(issues),
        },
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
