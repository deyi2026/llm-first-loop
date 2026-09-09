#!/usr/bin/env python3
"""Read-only CLI for LFL Runtime Causal Flight Recorder."""

from __future__ import annotations

import argparse
import json

from llm_loop.config import load_settings
from llm_loop.event_log.store import EventStore
from llm_loop.runtime.causal_diagnose import diagnose_event_store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True, help="session id")
    parser.add_argument("--attempt-id", default="", help="optional exact recorded attempt id")
    parser.add_argument("--events-dir", default="", help="override EventStore directory")
    args = parser.parse_args()
    settings = load_settings()
    store = EventStore(args.events_dir or settings.event_logs_dir, enabled=True)
    result = diagnose_event_store(store, args.session, target_attempt_id=args.attempt_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False))
    return 0 if result.get("status") not in {"read_failed", "session_required"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
