"""Real-browser canary for LFL-session -> ChatGPT conversation bindings.

The harness deliberately uses an isolated BrowserSurfaceLeaseStore and
ChatGPTSessionBindingStore.  It reads only the existing production surface
lease's Project identity/profile as bootstrap metadata; it never mutates the
production lease or session-binding store.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path

from llm_loop.core.run_context import current_session_id
from llm_loop.llm.chatgpt_page import ChatGPTPageAdapter
from llm_loop.llm.chatgpt_surface import (
    BrowserSurfaceLeaseStore,
    ChatGPTSessionBindingStore,
    ChatGPTSurface,
)
from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport
from llm_loop.llm.chatgpt_web import ChatGPTWebModelClient, _SurfaceOwnedTransport


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lease",
        default="data/chatgpt-web-provider/surface-lease.json",
    )
    parser.add_argument(
        "--root",
        default="/tmp/lfl-chatgpt-session-binding-canary",
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:9229")
    parser.add_argument("--reasoning", default="high")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-chars", type=int, default=150_000)
    return parser.parse_args()


def main() -> int:
    args = _args()
    production_lease = json.loads(Path(args.lease).read_text(encoding="utf-8"))
    root = Path(args.root).expanduser().resolve()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    project_url = str(production_lease["project_url"])
    project_ref = str(production_lease["project_ref"])
    profile = str(production_lease["profile_label"])

    surface = ChatGPTSurface(
        args.endpoint,
        lease_store=BrowserSurfaceLeaseStore(root / "surface"),
        project_url=project_url,
        project_ref=project_ref,
        profile_label=profile,
    )
    page = surface.open()
    project_name = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not project_name:
        labels = page.locator("[aria-label]").evaluate_all(
            """els => els
            .filter(e => { const r=e.getBoundingClientRect(); return r.width>0&&r.height>0; })
            .map(e => e.getAttribute('aria-label'))
            .filter(Boolean)"""
        )
        for label in labels:
            match = re.fullmatch(r"在“(.+)”中新建聊天", str(label))
            if match:
                project_name = match.group(1)
                break
        if not project_name:
            page.wait_for_timeout(150)
    if not project_name:
        raise RuntimeError("could not discover ChatGPT Project composer name")
    adapter = ChatGPTPageAdapter(
        page,
        profile_label=profile,
        project_name=project_name,
    )
    inner = ChatGPTWebPageTransport(
        adapter,
        turn_timeout_s=args.timeout,
        max_request_chars=args.max_chars,
    )
    store = ChatGPTSessionBindingStore(root / "sessions")
    transport = _SurfaceOwnedTransport(
        inner,
        surface=surface,
        adapter=adapter,
        session_store=store,
        project_ref=project_ref,
        segment_max_chars=int(args.max_chars * 0.75),
        segment_max_requests=8,
        reasoning_effort=args.reasoning,
    )
    client = ChatGPTWebModelClient(
        transport,
        reasoning_effort=args.reasoning,
        max_request_chars=args.max_chars,
    )

    def call(session_id: str, label: str):
        token = current_session_id.set(session_id)
        try:
            response = client.chat(
                [
                    {
                        "role": "user",
                        "content": (
                            f"Return exactly {label} as the final content. "
                            "Do not call tools."
                        ),
                    }
                ],
                [],
                timeout_s=args.timeout,
            )
        finally:
            current_session_id.reset(token)
        binding = store.load(session_id)
        if binding is None:
            raise RuntimeError(f"missing session binding after call: {session_id}")
        print(
            json.dumps(
                {
                    "label": label,
                    "content": response.content,
                    "conversation_id": binding.conversation_id,
                    "segment_seq": binding.segment_seq,
                    "segment_request_count": binding.segment_request_count,
                    "total_request_count": binding.total_request_count,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return binding

    try:
        a1 = call("canary-session-A", "CANARY_A1")
        a2 = call("canary-session-A", "CANARY_A2")
        b1 = call("canary-session-B", "CANARY_B1")
        a3 = call("canary-session-A", "CANARY_A3")
        verdict = {
            "same_session_reused": a1.conversation_id == a2.conversation_id,
            "different_session_separated": a1.conversation_id != b1.conversation_id,
            "switch_back_restored": a1.conversation_id == a3.conversation_id,
            "a_segment_seq": a3.segment_seq,
            "a_segment_request_count": a3.segment_request_count,
            "a_total_request_count": a3.total_request_count,
            "b_segment_request_count": b1.segment_request_count,
        }
        print("VERDICT " + json.dumps(verdict, sort_keys=True), flush=True)
        return 0 if all(
            verdict[key]
            for key in (
                "same_session_reused",
                "different_session_separated",
                "switch_back_restored",
            )
        ) else 2
    finally:
        try:
            if surface.page is not None:
                surface.page.close()
        finally:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
