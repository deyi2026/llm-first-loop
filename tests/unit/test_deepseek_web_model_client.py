from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from llm_loop.core.run_context import current_reasoning_effort
from llm_loop.llm.chatgpt_page import PageBinding
from llm_loop.llm.deepseek_transport import DeepSeekWebPageTransport
from llm_loop.llm.deepseek_web import (
    MODEL_PROTOCOL,
    DeepSeekModelProtocolError,
    DeepSeekWebModelClient,
    _SurfaceOwnedTransport,
)
from llm_loop.llm.errors import LLMRequestTooLargeError, is_overflow_error


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


def _tool():
    return {
        "content": None,
        "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "x"}}],
        "finish_reason": "tool_calls",
    }


def test_deepseek_web_model_client_maps_lfl_tool_calls():
    transport = _Transport([_tool()])
    client = DeepSeekWebModelClient(transport)
    response = client.chat([{"role": "user", "content": "read x"}], [{"type": "function"}])
    assert response.provider == "deepseek-web"
    assert response.finish_reason == "tool_calls"
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("c1", "read_file", {"path": "x"})
    ]


def test_deepseek_web_model_client_accepts_json_encoded_tool_arguments():
    transport = _Transport(
        [
            {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "name": "read_file", "arguments": '{"path":"x"}'}
                ],
                "finish_reason": "tool_calls",
            }
        ]
    )
    client = DeepSeekWebModelClient(transport)

    response = client.chat([{"role": "user", "content": "read x"}], [{"type": "function"}])

    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("c1", "read_file", {"path": "x"})
    ]


@pytest.mark.parametrize("arguments", ["not-json", "[]", '"text"', "null"])
def test_deepseek_web_model_client_rejects_non_object_encoded_tool_arguments(arguments):
    transport = _Transport(
        [
            {
                "content": None,
                "tool_calls": [
                    {"id": "c1", "name": "read_file", "arguments": arguments}
                ],
                "finish_reason": "tool_calls",
            }
        ]
    )
    client = DeepSeekWebModelClient(transport)

    with pytest.raises(DeepSeekModelProtocolError, match="arguments string"):
        client.chat([{"role": "user", "content": "read x"}], [{"type": "function"}])


def test_deepseek_request_local_reasoning_is_transport_only():
    transport = _Transport([_final("ok")])
    client = DeepSeekWebModelClient(transport)
    token = current_reasoning_effort.set("instant")
    try:
        assert client.chat([{"role": "user", "content": "x"}], []).content == "ok"
    finally:
        current_reasoning_effort.reset(token)
    request = transport.requests[0][0]
    assert request["_reasoning_effort"] == "instant"
    assert '"_reasoning_effort"' not in DeepSeekWebPageTransport._render_request(request)


def test_deepseek_ignores_reasoning_effort_not_declared_by_web_provider():
    transport = _Transport([_final("ok")])
    client = DeepSeekWebModelClient(transport)
    token = current_reasoning_effort.set("xhigh")
    try:
        client.chat([{"role": "user", "content": "x"}], [])
    finally:
        current_reasoning_effort.reset(token)
    assert transport.requests[0][0]["_reasoning_effort"] is None


def test_deepseek_preflight_uses_exact_renderer_and_90_percent_soft_limit():
    client = DeepSeekWebModelClient(_Transport([]), max_request_chars=10_000)
    messages = [{"role": "user", "content": "x" * 8_000}]
    facts = client.request_envelope_preflight(messages, [])
    rendered = DeepSeekWebPageTransport._render_request(
        {
            "protocol": MODEL_PROTOCOL,
            "request_id": "lfl-model-0000",
            "model": "web-deepseek",
            "messages": messages,
            "tools": [],
        }
    )
    assert facts["observed_chars"] == len(rendered)
    assert facts["soft_limit_chars"] == 9_000
    assert facts["hard_limit_chars"] == 10_000


def test_deepseek_request_wrapper_keeps_lfl_tool_authority_and_disables_native_tools():
    rendered = DeepSeekWebPageTransport._render_request(
        {
            "protocol": MODEL_PROTOCOL,
            "request_id": "lfl-model-0001",
            "model": "web-deepseek",
            "messages": [{"role": "user", "content": "current facts?"}],
            "tools": [{"type": "function", "function": {"name": "search_files"}}],
        }
    )
    assert "not an ordinary DeepSeek conversation" in rendered
    assert "outer DeepSeek web thread is transport-only" in rendered
    assert "LFL is the sole authority" in rendered
    assert "never use DeepSeek Smart Search" in rendered
    assert '"name":"search_files"' in rendered


def test_deepseek_rendered_code_fallback_allows_qualified_ui_chrome():
    raw = DeepSeekWebPageTransport._extract_rendered_response_text(  # noqa: SLF001
        'lfl-model-response\n复制\n下载\n'
        '{"protocol":"lfl-model/0.1","request_id":"r1","content":"ok",'
        '"tool_calls":[],"finish_reason":"stop"}'
    )
    assert json.loads(raw)["content"] == "ok"


def test_deepseek_rendered_code_fallback_rejects_extra_prose():
    with pytest.raises(DeepSeekModelProtocolError, match="unexpected"):
        DeepSeekWebPageTransport._extract_rendered_response_text(  # noqa: SLF001
            'lfl-model-response\nuntrusted prose\n'
            '{"protocol":"lfl-model/0.1","request_id":"r1","content":"ok",'
            '"tool_calls":[],"finish_reason":"stop"}'
        )


def test_deepseek_rendered_tag_fallback_accepts_single_json_object():
    raw = DeepSeekWebPageTransport._extract_rendered_response_text(  # noqa: SLF001
        '<lfl-model-response> {"protocol":"lfl-model/0.1","request_id":"r1",'
        '"content":"","tool_calls":[{"id":"c1","name":"read_file",'
        '"arguments":{"path":"x"}}],"finish_reason":"tool_calls"} '
        '</lfl-model-response>'
    )
    assert json.loads(raw)["tool_calls"][0]["arguments"] == {"path": "x"}


@pytest.mark.parametrize(
    "text",
    [
        '<lfl-model-response>{"protocol":"lfl-model/0.1"}',
        '<lfl-model-response>{"protocol":"lfl-model/0.1"} trailing</lfl-model-response>',
        'prefix <lfl-model-response>{"protocol":"lfl-model/0.1"}</lfl-model-response>',
    ],
)
def test_deepseek_rendered_tag_fallback_rejects_malformed_or_extra_text(text):
    with pytest.raises(DeepSeekModelProtocolError):
        DeepSeekWebPageTransport._extract_rendered_response_text(text)  # noqa: SLF001


def test_deepseek_dsml_tool_response_normalizes_exact_lfl_tool_call():
    request = {
        "protocol": "lfl-model/0.1",
        "request_id": "lfl-model-0004",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_evidence",
                    "parameters": {"type": "object"},
                },
            }
        ],
    }
    text = "\n".join(
        [
            "<｜｜DSML｜｜ calls>",
            '<｜｜DSML｜｜ invoke name="read_evidence">',
            '<｜｜DSML｜｜ parameter name="evidence_ref" string="true">evidence://v1/abc</｜｜DSML｜｜ parameter>',
            '<｜｜DSML｜｜ parameter name="range_type" string="true">line</｜｜DSML｜｜ parameter>',
            '<｜｜DSML｜｜ parameter name="start" string="false">0</｜｜DSML｜｜ parameter>',
            '<｜｜DSML｜｜ parameter name="limit" string="false">200</｜｜DSML｜｜ parameter>',
            "</｜｜DSML｜｜ invoke>",
            "</｜｜DSML｜｜ calls>",
        ]
    )

    value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
        text,
        request=request,
    )

    assert value == {
        "protocol": "lfl-model/0.1",
        "request_id": "lfl-model-0004",
        "content": "",
        "tool_calls": [
            {
                "id": "lfl-model-0004-dsml-1",
                "name": "read_evidence",
                "arguments": {
                    "evidence_ref": "evidence://v1/abc",
                    "range_type": "line",
                    "start": 0,
                    "limit": 200,
                },
            }
        ],
        "finish_reason": "tool_calls",
    }


def test_deepseek_dsml_tool_response_unwraps_observed_tool_call_envelope():
    request = {
        "request_id": "lfl-model-0005",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "workdir": {"type": "string"},
                        },
                        "required": ["command"],
                    },
                },
            }
        ],
    }
    text = "\n".join(
        [
            "<｜｜DSML｜｜ calls>",
            '<｜｜DSML｜｜ invoke name="execute_command">',
            '<｜｜DSML｜｜ parameter name="arguments" string="false">'
            '{"command":"printf ok","workdir":"/tmp"}'
            '</｜｜DSML｜｜ parameter>',
            '<｜｜DSML｜｜ parameter name="id" string="true">lfl-0005-c1</｜｜DSML｜｜ parameter>',
            '<｜｜DSML｜｜ parameter name="name" string="true">execute_command</｜｜DSML｜｜ parameter>',
            '<｜｜DSML｜｜ parameter name="type" string="true">function</｜｜DSML｜｜ parameter>',
            "</｜｜DSML｜｜ invoke>",
            "</｜｜DSML｜｜ calls>",
        ]
    )

    value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
        text,
        request=request,
    )

    assert value["tool_calls"] == [
        {
            "id": "lfl-0005-c1",
            "name": "execute_command",
            "arguments": {"command": "printf ok", "workdir": "/tmp"},
        }
    ]


def test_deepseek_dsml_tool_response_accepts_multiline_envelope_parameter_body():
    request = {
        "request_id": "lfl-model-0006",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "workdir": {"type": "string"},
                        },
                    },
                },
            }
        ],
    }
    wrapped = json.dumps(
        {
            "command": "cd /tmp\ncat > /tmp/probe.py <<'PY'\nprint('ok')\nPY\npython3 /tmp/probe.py",
            "workdir": "/tmp",
        },
        ensure_ascii=False,
        indent=2,
    )
    text = (
        "<｜｜DSML｜｜ calls>\n"
        '<｜｜DSML｜｜ invoke name="execute_command">\n'
        '<｜｜DSML｜｜ parameter name="arguments" string="false">\n'
        f"{wrapped}\n"
        "</｜｜DSML｜｜ parameter>\n"
        '<｜｜DSML｜｜ parameter name="name" string="true">execute_command</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>\n"
        "</｜｜DSML｜｜ calls>"
    )

    value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
        text,
        request=request,
    )

    assert value["tool_calls"][0]["arguments"] == {
        "command": "cd /tmp\ncat > /tmp/probe.py <<'PY'\nprint('ok')\nPY\npython3 /tmp/probe.py",
        "workdir": "/tmp",
    }


def test_deepseek_dsml_tool_response_unwraps_json_encoded_envelope_arguments():
    request = {
        "request_id": "lfl-model-0007",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
                },
            }
        ],
    }
    inner = json.dumps({"command": "printf encoded"})
    text = (
        "<｜｜DSML｜｜ calls>\n"
        '<｜｜DSML｜｜ invoke name="execute_command">\n'
        f'<｜｜DSML｜｜ parameter name="arguments" string="true">{inner}</｜｜DSML｜｜ parameter>\n'
        '<｜｜DSML｜｜ parameter name="name" string="true">execute_command</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>\n"
        "</｜｜DSML｜｜ calls>"
    )

    value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
        text,
        request=request,
    )

    assert value["tool_calls"][0]["arguments"] == {"command": "printf encoded"}


def test_deepseek_dsml_tool_response_recovers_rendered_shell_quotes_in_envelope():
    request = {
        "request_id": "lfl-model-0007b",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "workdir": {"type": "string"},
                        },
                        "required": ["command"],
                    },
                },
            }
        ],
    }
    # This is the exact failure class observed in the DeepSeek page: quote escaping
    # inside the shell command was removed by the rendered DSML representation.
    raw_arguments = (
        '{"command": "cd /tmp && grep -m4 \'"event": "failed"\' journal.jsonl", '
        '"workdir": "/tmp"}'
    )
    text = (
        "<｜｜DSML｜｜ calls>\n"
        '<｜｜DSML｜｜ invoke name="execute_command">\n'
        '<｜｜DSML｜｜ parameter name="arguments" string="false">'
        f"{raw_arguments}"
        "</｜｜DSML｜｜ parameter>\n"
        '<｜｜DSML｜｜ parameter name="name" string="true">execute_command</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>\n"
        "</｜｜DSML｜｜ calls>"
    )

    value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
        text,
        request=request,
    )

    assert value["tool_calls"][0]["arguments"] == {
        "command": 'cd /tmp && grep -m4 \'"event": "failed"\' journal.jsonl',
        "workdir": "/tmp",
    }


def test_deepseek_dsml_tool_response_recovers_literal_multiline_shell_string():
    request = {
        "request_id": "lfl-model-0007c",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "workdir": {"type": "string"},
                        },
                    },
                },
            }
        ],
    }
    command = "cd /tmp\ncat > /tmp/probe.py <<'PY'\nprint('ok')\nPY\npython3 /tmp/probe.py"
    raw_arguments = '{"command": "' + command + '", "workdir": "/tmp"}'
    text = (
        "<｜｜DSML｜｜ calls>\n"
        '<｜｜DSML｜｜ invoke name="execute_command">\n'
        '<｜｜DSML｜｜ parameter name="arguments" string="false">'
        f"{raw_arguments}"
        "</｜｜DSML｜｜ parameter>\n"
        '<｜｜DSML｜｜ parameter name="name" string="true">execute_command</｜｜DSML｜｜ parameter>\n'
        "</｜｜DSML｜｜ invoke>\n"
        "</｜｜DSML｜｜ calls>"
    )

    value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
        text,
        request=request,
    )

    assert value["tool_calls"][0]["arguments"] == {
        "command": command,
        "workdir": "/tmp",
    }


@pytest.mark.parametrize(
    "text",
    [
        '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="unknown">\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>',
        'prefix\n<｜｜DSML｜｜ calls>\n</｜｜DSML｜｜ calls>',
        '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="read_evidence">\n'
        '<｜｜DSML｜｜ parameter name="start" string="false">not-json</｜｜DSML｜｜ parameter>\n'
        '</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>',
    ],
)
def test_deepseek_dsml_tool_response_rejects_untrusted_or_ambiguous_shapes(text):
    request = {
        "request_id": "lfl-model-0004",
        "tools": [{"type": "function", "function": {"name": "read_evidence"}}],
    }
    with pytest.raises(DeepSeekModelProtocolError):
        value = DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
            text,
            request=request,
        )
        if value is None:
            raise DeepSeekModelProtocolError("not a DSML calls block")


@pytest.mark.parametrize(
    "text, match",
    [
        (
            '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="execute_command">\n'
            '<｜｜DSML｜｜ parameter name="arguments" string="false">{"command":"ok"}</｜｜DSML｜｜ parameter>\n'
            '<｜｜DSML｜｜ parameter name="name" string="true">read_file</｜｜DSML｜｜ parameter>\n'
            '</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>',
            "name does not match",
        ),
        (
            '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="execute_command">\n'
            '<｜｜DSML｜｜ parameter name="arguments" string="true">[]</｜｜DSML｜｜ parameter>\n'
            '</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>',
            "must decode to an object",
        ),
        (
            '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="execute_command">\n'
            '<｜｜DSML｜｜ parameter name="arguments" string="false">{"command":"ok"}</｜｜DSML｜｜ parameter>\n'
            '<｜｜DSML｜｜ parameter name="extra" string="true">x</｜｜DSML｜｜ parameter>\n'
            '</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>',
            "unexpected",
        ),
    ],
)
def test_deepseek_dsml_tool_response_rejects_invalid_envelopes(text, match):
    request = {
        "request_id": "lfl-model-0008",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                    },
                },
            }
        ],
    }
    with pytest.raises(DeepSeekModelProtocolError, match=match):
        DeepSeekWebPageTransport._extract_dsml_tool_response(  # noqa: SLF001
            text,
            request=request,
        )


def test_deepseek_surface_owned_transport_resets_and_mechanically_controls_each_request():
    events = []

    class Surface:
        def reset_to_root(self): events.append("reset")
        def bind_conversation(self, binding): events.append(f"bind:{binding.conversation_id}")
        def close(self): events.append("surface-close")

    class Adapter:
        def require_ready(self): events.append("ready")
        def ensure_runtime_controls(self, effort): events.append(f"controls:{effort}")
        def observe_identity(self):
            return SimpleNamespace(conversation_id="conversation-new")

    class Inner:
        def rebind(self): events.append("rebind")
        def exchange(self, request, *, timeout_s=None):
            events.append(f"exchange:{request['request_id']}")
            return {"request_id": request["request_id"]}
        def close(self): events.append("inner-close")

    transport = _SurfaceOwnedTransport(Inner(), surface=Surface(), adapter=Adapter())
    transport.exchange({"request_id": "r1"})
    transport.exchange({"request_id": "r2", "_reasoning_effort": "instant"})
    transport.close()
    assert events == [
        "reset", "ready", "controls:high", "rebind", "exchange:r1", "bind:conversation-new",
        "reset", "ready", "controls:instant", "rebind", "exchange:r2", "bind:conversation-new",
        "inner-close", "surface-close",
    ]


def test_deepseek_hard_guard_fails_before_browser_send_and_counts_as_overflow():
    sent = []
    binding = PageBinding(
        profile_label="fixture",
        url="https://chat.deepseek.com/",
        title="DeepSeek",
        project_ref="deepseek-web",
        conversation_id=None,
    )

    class Adapter:
        def require_binding(self, _binding): return binding
        def observe_generation(self):
            return SimpleNamespace(assistant_count=0, latest_assistant_identity=None)
        def send_text(self, text, **_kwargs):
            sent.append(text)
            raise AssertionError("browser send must not run")

    transport = DeepSeekWebPageTransport(Adapter(), binding=binding, max_request_chars=100)
    with pytest.raises(LLMRequestTooLargeError) as caught:
        transport.exchange(
            {
                "protocol": MODEL_PROTOCOL,
                "request_id": "too-large",
                "model": "web-deepseek",
                "messages": [{"role": "user", "content": "x" * 500}],
                "tools": [],
            }
        )
    assert sent == []
    assert caught.value.provider == "deepseek-web"
    assert caught.value.limit_chars == 100
    assert is_overflow_error(caught.value) is True


def test_deepseek_transport_rejects_native_search_even_if_model_payload_is_valid():
    binding = PageBinding(
        profile_label="fixture",
        url="https://chat.deepseek.com/",
        title="DeepSeek",
        project_ref="deepseek-web",
        conversation_id=None,
    )

    class Adapter:
        def require_binding(self, _binding): return binding
        def observe_generation(self):
            return SimpleNamespace(assistant_count=0, latest_assistant_identity=None)
        def send_text(self, _text, **_kwargs):
            return SimpleNamespace(conversation_id="a", user_message_identity="u")
        def observe_identity(self):
            return PageBinding("fixture", "https://chat.deepseek.com/a/chat/s/a", "x", "deepseek-web", "a")
        def wait_for_assistant_completion(self, *_args, **_kwargs):
            return SimpleNamespace(streaming=False)
        def observe_native_tool_activity(self):
            return SimpleNamespace(web_search_detected=True)

    transport = DeepSeekWebPageTransport(Adapter(), binding=binding)
    with pytest.raises(DeepSeekModelProtocolError, match="Smart Search"):
        transport.exchange(
            {
                "protocol": MODEL_PROTOCOL,
                "request_id": "r1",
                "model": "web-deepseek",
                "messages": [{"role": "user", "content": "x"}],
                "tools": [],
            }
        )
