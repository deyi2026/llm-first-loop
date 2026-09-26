import pytest

from llm_loop.llm.chatgpt_web import (
    MODEL_PROTOCOL,
    ChatGPTModelProtocolError,
    ChatGPTWebModelClient,
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
