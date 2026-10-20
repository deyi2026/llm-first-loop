"""Per-model repair profiles preserve source protocol state without global heuristics."""
import json
from pathlib import Path

import pytest

from llm_loop.config import Settings
from llm_loop.core.history import _apply_reasoning_tail
from llm_loop.core.loop.build import _reasoning_tail_for
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.run_context import current_reasoning_effort, current_reasoning_mode
from llm_loop.llm.client import LLMClient
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import load_registry

PROFILE = Path(__file__).resolve().parents[2] / "docs/config/local-model-reasoning-recovery-20261021.json"


@pytest.mark.parametrize("model", ["qwen3.8-flash-next", "ornith-ai/Ornith-1.5-35B-A3B-MLX"])
def test_explicit_repair_profile_preserves_protocol_and_operator_budgets(model, monkeypatch):
    monkeypatch.delenv("LOCAL_ENABLE_THINKING", raising=False)
    patches = json.loads(PROFILE.read_text())["model_patches"]
    raw = {"local-test": {"base_url": "http://127.0.0.1:8901/v1", "api_key_env": "",
        "max_input_tokens": 184000, "models": {
            model: {"context": 65536, "max_tokens": 32768, "thinking": True,
                    "reasoning_capable": True, **patches[model]},
            "unrelated": {"context": 8192, "temperature": 0.0, "reasoning_replay": "none"},
        }, "default_model": model}}
    settings = Settings(llm_api_key="", llm_base_url="https://default.invalid/v1", llm_model="default",
                        model_providers_raw=json.dumps(raw), reasoning_tail=-2)
    registry = load_registry(settings)
    spec = registry.providers["local-test"].models[model]
    assert spec.context == 65536 and spec.max_tokens == 32768
    assert registry.providers["local-test"].max_input_tokens == 184000
    assert spec.temperature is None
    other = registry.providers["local-test"].models["unrelated"]
    assert other.temperature == 0.0 and other.reasoning_replay == "none"
    source = Message(role="assistant", content="", source=MessageSource.SYSTEM,
        reasoning_content="EXACT TOOL PLAN", tool_calls=[{"id": "c", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"source.py"}'}}])
    policy = _reasoning_tail_for(settings, resolved_label="local-test/" + model,
                                  registry_snapshot=registry)
    projected = _apply_reasoning_tail([source], policy)[0].to_llm_dict()
    assert projected["reasoning_content"] == "EXACT TOOL PLAN"
    assert projected["tool_calls"] == source.tool_calls
    default = LLMClient(api_key="", base_url="https://default.invalid/v1", model="default",
                        temperature=0.0, reasoning_effort="max")
    pool = ModelClientPool(registry=registry, default_client=default)
    mode = current_reasoning_mode.set("auto")
    effort = current_reasoning_effort.set("max")
    try:
        client = pool.get_client("local-test/" + model)
        assert client.temperature is None and client.max_tokens == 32768
        if model == "qwen3.8-flash-next":
            assert client._openai_chat_template_kwargs() == {"reasoning_effort": "xhigh"}
        else:
            # No effort or sampling recipe is borrowed from Qwen for unloaded MLX.
            assert not client.reasoning_effort_map
    finally:
        current_reasoning_effort.reset(effort)
        current_reasoning_mode.reset(mode)
        pool.close()
        default.close()
