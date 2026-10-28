#!/usr/bin/env python3
"""Write the gate result into docs/STATUS.json so documents cite one source.

    python3 tools/update_status.py build/source-checks.json [--date YYYY-MM-DD]

Only the ``gate.last_local_result`` block and ``updated_at`` change; plan and
spec statuses stay a human decision. The tool never grants acceptance.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "STATUS.json"


def gate_summary(report: dict, *, measured_on: str) -> dict:
    tests = report.get("tests", {})
    return {"platform_set": report.get("platform_set"),
            "discovered": tests.get("discovered"), "passed": tests.get("passed"),
            "skipped": len(tests.get("skipped", [])),
            "failed": len(tests.get("failures", [])) + len(tests.get("errors", [])),
            "status": report.get("status"), "measured_on": measured_on}


def update(report_path, *, date=None, status_path=STATUS):
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    status = json.loads(Path(status_path).read_text(encoding="utf-8"))
    day = date or _dt.date.today().isoformat()
    previous = status["gate"].get("last_local_result", {})
    status["gate"]["last_local_result"] = {**gate_summary(report, measured_on=day),
                                           **({"note": previous["note"]} if "note" in previous else {})}
    status["updated_at"] = day
    Path(status_path).write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report")
    parser.add_argument("--date")
    parser.add_argument("--status", default=str(STATUS), help="status file to update (default docs/STATUS.json)")
    args = parser.parse_args(argv)
    status = update(args.report, date=args.date, status_path=Path(args.status))
    print(json.dumps(status["gate"]["last_local_result"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
