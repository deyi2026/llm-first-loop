import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from llm_loop.llm.chatgpt_page import PageBinding
from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport
from llm_loop.llm.chatgpt_web import (
    MODEL_PROTOCOL,
    ChatGPTModelProtocolError,
    ChatGPTWebModelClient,
    _SurfaceOwnedTransport,
    _ThreadBoundTransport,
)


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def exchange(self, request, *, timeout_s=None):
        self.requests.append((request, timeout_s))
        response = dict(self.responses.pop(0))
        response.setdefault("protocol", MODEL_PROTOCOL)
        response.setdefault("request_id", request["request_id"])
        return response


def _final(content="done"):
    return {"content": content, "tool_calls": [], "finish_reason": "stop"}


def _tool(name="read_file", call_id="c1", arguments=None):
    return {
        "content": None,
        "tool_calls": [{"id": call_id, "name": name, "arguments": arguments or {"path": "x"}}],
        "finish_reason": "tool_calls",
    }


def test_chatgpt_web_model_client_maps_provider_tool_call_to_lfl_response():
    transport = _Transport([_tool()])
    client = ChatGPTWebModelClient(transport)
    response = client.chat([{"role": "user", "content": "read x"}], [{"type": "function"}])
    assert response.provider == "chatgpt-web"
    assert response.finish_reason == "tool_calls"
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("c1", "read_file", {"path": "x"})
    ]
    request = transport.requests[0][0]
    assert request["protocol"] == MODEL_PROTOCOL
    assert request["messages"][0]["content"] == "read x"


def test_chatgpt_web_model_client_maps_final_content():
    client = ChatGPTWebModelClient(_Transport([_final("answer")]))
    response = client.chat([{"role": "user", "content": "x"}], [])
    assert response.content == "answer"
    assert response.tool_calls == []
    assert response.finish_reason == "stop"


@pytest.mark.parametrize(
    "response,match",
    [
        ({"protocol": "wrong", "request_id": "ignored", **_final()}, "wrong protocol"),
        ({"content": None, "tool_calls": [], "finish_reason": "stop"}, "non-empty content"),
        (
            {
                "content": None,
                "tool_calls": [{"id": "c1", "name": "x", "arguments": {}}],
                "finish_reason": "stop",
            },
            "finish_reason=tool_calls",
        ),
    ],
)
def test_chatgpt_web_model_client_fails_closed_on_invalid_response(response, match):
    transport = _Transport([response])
    client = ChatGPTWebModelClient(transport)
    if response.get("protocol") == "wrong":
        # Preserve the deliberately wrong protocol instead of helper defaulting it.
        transport.responses[0]["request_id"] = "lfl-model-0001"
    with pytest.raises(ChatGPTModelProtocolError, match=match):
        client.chat([{"role": "user", "content": "x"}], [])


def test_thread_bound_transport_keeps_builder_exchange_and_close_on_one_thread():
    lifecycle_threads: list[tuple[str, int]] = []

    class AffinityTransport:
        def __init__(self):
            self.owner = threading.get_ident()
            lifecycle_threads.append(("build", self.owner))

        def exchange(self, request, *, timeout_s=None):
            current = threading.get_ident()
            assert current == self.owner
            lifecycle_threads.append(("exchange", current))
            return {"request_id": request["request_id"], "timeout_s": timeout_s}

        def close(self):
            current = threading.get_ident()
            assert current == self.owner
            lifecycle_threads.append(("close", current))

    transport = _ThreadBoundTransport(AffinityTransport)

    def call(i: int):
        return transport.exchange({"request_id": str(i)}, timeout_s=float(i))

    # Simulate FastAPI handing consecutive requests to unrelated worker threads.
    with ThreadPoolExecutor(max_workers=3) as callers:
        results = list(callers.map(call, range(1, 5)))

    assert [row["request_id"] for row in results] == ["1", "2", "3", "4"]
    transport.close()
    assert [kind for kind, _ in lifecycle_threads] == [
        "build",
        "exchange",
        "exchange",
        "exchange",
        "exchange",
        "close",
    ]
    assert len({thread_id for _, thread_id in lifecycle_threads}) == 1


def test_chatgpt_web_request_wrapper_preserves_lfl_role_and_tool_authority():
    rendered = ChatGPTWebPageTransport._render_request(
        {
            "protocol": MODEL_PROTOCOL,
            "request_id": "lfl-model-0001",
            "model": "web-gpt",
            "messages": [
                {"role": "system", "content": "current runtime facts require evidence"},
                {"role": "user", "content": "你是什么模型"},
            ],
            "tools": [{"type": "function", "function": {"name": "model_catalog"}}],
        }
    )

    assert "not an ordinary ChatGPT conversation" in rendered
    assert "preserve role semantics" in rendered
    assert "role=system are LFL system instructions" in rendered
    assert "already been composed by LFL context management" in rendered
    assert "Rule/Method/Experience/Memory/Docs/Skill" in rendered
    assert "do not use earlier messages from the outer ChatGPT conversation" in rendered
    assert "Do not substitute facts about the outer ChatGPT web session" in rendered
    assert "request.tools are LFL tools" in rendered
    assert "instead of answering from your own identity" in rendered
    assert '"name":"model_catalog"' in rendered


def test_surface_owned_transport_starts_every_exchange_from_fresh_outer_thread():
    events: list[str] = []

    class Surface:
        def reset_to_project_root(self):
            events.append("reset")

        def bind_conversation(self, binding):
            events.append(f"bind:{binding.conversation_id}")

        def close(self):
            events.append("surface-close")

    class Adapter:
        def ensure_reasoning_effort(self, effort):
            events.append(f"reasoning:{effort}")

        def observe_identity(self):
            return type("Binding", (), {"conversation_id": "conversation-new"})()

    class Inner:
        def rebind(self):
            events.append("rebind")

        def exchange(self, request, *, timeout_s=None):
            events.append(f"exchange:{request['request_id']}")
            return {"request_id": request["request_id"]}

        def close(self):
            events.append("inner-close")

    transport = _SurfaceOwnedTransport(Inner(), surface=Surface(), adapter=Adapter())
    assert transport.exchange({"request_id": "r1"}) == {"request_id": "r1"}
    assert transport.exchange({"request_id": "r2"}) == {"request_id": "r2"}
    transport.close()

    assert events == [
        "reset",
        "reasoning:high",
        "rebind",
        "exchange:r1",
        "bind:conversation-new",
        "reset",
        "reasoning:high",
        "rebind",
        "exchange:r2",
        "bind:conversation-new",
        "inner-close",
        "surface-close",
    ]


def test_page_transport_uses_turn_budget_for_post_click_send_confirmation():
    sent: list[dict] = []
    binding = PageBinding(
        profile_label="fixture",
        url="https://chatgpt.com/g/project/c/conversation",
        title="fixture",
        project_ref="project",
        conversation_id="conversation",
    )

    class Adapter:
        def require_binding(self, observed):
            assert observed == binding

        def observe_generation(self):
            return SimpleNamespace(assistant_count=0, latest_assistant_identity=None)

        def send_text(self, text, **kwargs):
            sent.append({"text": text, **kwargs})
            return SimpleNamespace(
                conversation_id="conversation",
                user_message_identity="user-1",
            )

        def wait_for_assistant_completion(self, *_args, **_kwargs):
            return SimpleNamespace(streaming=False)

        def observe_native_tool_activity(self):
            return SimpleNamespace(latest_assistant_citation_count=0)

        def observe_latest_code_blocks(self):
            return [
                SimpleNamespace(
                    language="lfl-model-response",
                    text=(
                        '{"protocol":"lfl-model/0.1","request_id":"r1",'
                        '"content":"ok","tool_calls":[],"finish_reason":"stop"}'
                    ),
                )
            ]

    transport = ChatGPTWebPageTransport(
        Adapter(),
        binding=binding,
        turn_timeout_s=120.0,
        send_timeout_s=30.0,
    )
    response = transport.exchange(
        {
            "protocol": MODEL_PROTOCOL,
            "request_id": "r1",
            "model": "web-gpt",
            "messages": [{"role": "user", "content": "x"}],
            "tools": [],
        },
        timeout_s=120.0,
    )

    assert response["content"] == "ok"
    assert sent[0]["timeout_s"] == 30.0
    assert sent[0]["confirm_timeout_s"] == 120.0


def test_chatgpt_web_wire_keeps_stable_tools_before_dynamic_dialogue_and_request_id():
    base = {
        "protocol": MODEL_PROTOCOL,
        "request_id": "r1",
        "model": "web-gpt",
        "messages": [{"content": "first", "role": "user"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "parameters": {"required": ["path"], "type": "object"},
                    "name": "read_file",
                },
            }
        ],
    }
    other = {**base, "request_id": "r2", "messages": [{"role": "user", "content": "second"}]}

    rendered = ChatGPTWebPageTransport._render_request(base)
    assert rendered.index('"tools"') < rendered.index('"messages"') < rendered.index('"request_id"')

    first = ChatGPTWebPageTransport._prefix_diagnostics(base)
    second = ChatGPTWebPageTransport._prefix_diagnostics(other)
    assert first["stable_prefix_sha256"] == second["stable_prefix_sha256"]
    assert first["stable_prefix_chars"] == second["stable_prefix_chars"]
    assert first["request_payload_sha256"] != second["request_payload_sha256"]
    assert first["authoritative"] is False
