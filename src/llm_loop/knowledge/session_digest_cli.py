"""Explicit offline digest file export/show/hydrate; no model or startup producer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_loop.event_log.store import EventStore
from llm_loop.knowledge.session_digest import SessionDigest, SessionDigestReader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--start-seq", type=int, default=1)
    build.add_argument("--end-seq", type=int)
    build.add_argument("--preview-chars", type=int, default=240)
    show = sub.add_parser("show")
    show.add_argument("--format", choices=("json", "markdown"), default="json")
    show.add_argument("--start", type=int, default=0)
    show.add_argument("--limit", type=int, default=20)
    hydrate = sub.add_parser("hydrate")
    hydrate.add_argument("--event-ref", required=True)
    hydrate.add_argument("--start", type=int, default=0)
    hydrate.add_argument("--max-chars", type=int, default=4000)
    hydrate.add_argument("--event-sha256")
    for p in (show, hydrate):
        p.add_argument("--digest", type=Path, required=True)
    for p in (build, hydrate):
        p.add_argument("--events-dir", type=Path, required=True)
    for p in (build, show, hydrate):
        p.add_argument("--session-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action != "build":
            digest = SessionDigest.from_dict(json.loads(args.digest.read_text()))
            if digest.body["session_id"] != args.session_id:
                raise ValueError("digest is outside requested session scope")
        if args.action == "show":
            if args.format == "markdown":
                print(digest.render_markdown())
                return 0
            result = digest.page(start=args.start, limit=args.limit)
        else:
            reader = SessionDigestReader(EventStore(args.events_dir), args.session_id)
            if args.action == "build":
                result = reader.build(start_seq=args.start_seq, end_seq=args.end_seq,
                                      preview_chars=args.preview_chars).to_dict()
            else:
                result = reader.hydrate(digest, args.event_ref, start=args.start,
                                        max_chars=args.max_chars,
                                        expected_event_sha256=args.event_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("state") in {"unavailable", "source_changed"} else 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
