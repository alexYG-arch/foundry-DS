#!/usr/bin/env python3
"""Offline copy REVISION_V1 -> opt-in dedup store; source is read-only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness_foundry_factory.revision_store_dedup import migrate_to_dedup  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args(argv)
    try:
        result = migrate_to_dedup(args.source, args.target)
    except Exception as exc:
        result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "MIGRATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
