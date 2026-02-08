#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect JSONL trace logs.")
    parser.add_argument("--file", default="logs/trace.ndjson", help="Trace JSONL file path")
    parser.add_argument("--tail", type=int, default=120, help="Show only last N matching events")
    parser.add_argument("--trace-id", default="", help="Filter by a specific trace_id")
    parser.add_argument("--component", default="", help="Filter by component (server|engine|openai_judge|assets)")
    return parser.parse_args()


def load_records(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records: List[Dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def main() -> None:
    args = parse_args()
    path = Path(args.file)
    records = load_records(path)

    if args.trace_id:
        records = [r for r in records if str(r.get("trace_id")) == args.trace_id]
    if args.component:
        records = [r for r in records if str(r.get("component")) == args.component]

    if args.tail > 0:
        records = records[-args.tail :]

    if not records:
        print("No matching trace events.")
        return

    for rec in records:
        ts = rec.get("ts", "-")
        level = rec.get("level", "INFO")
        trace_id = rec.get("trace_id", "-")
        component = rec.get("component", "-")
        event = rec.get("event", "-")
        span_id = rec.get("span_id", "")
        extra = {k: v for k, v in rec.items() if k not in {"ts", "level", "trace_id", "component", "event", "span_id", "thread"}}
        suffix = f" span={span_id}" if span_id else ""
        print(f"{ts} [{level}] trace={trace_id} {component}.{event}{suffix}")
        if extra:
            print(f"  data={json.dumps(extra, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
