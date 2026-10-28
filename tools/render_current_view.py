#!/usr/bin/env python3
"""Render an A4 current-view envelope or one bounded page of it."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from harness_foundry_factory.rsi_handoff import HandoffError, paginate, render_markdown  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", type=Path)
    parser.add_argument("--section", choices=("changes", "affected_assertions", "evidence", "history_refs", "pending", "limitations"))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        view = json.loads(args.view.read_text(encoding="utf-8"))
        if args.section:
            result = paginate(view, args.section, args.offset, args.limit)
        else:
            result = {"markdown": render_markdown(view)}
    except (OSError, ValueError, HandoffError) as exc:
        result = {"status": "ERROR", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
