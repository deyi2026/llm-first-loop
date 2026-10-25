"""Agent/Web sharing and validation at the actual video tool adapter."""

import json

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.video_generation import VideoGenerationTool
from llm_loop.video.runtime import VideoConfig, VideoRuntime


def test_agent_sees_saved_web_configuration(tmp_path):
    runtime = VideoRuntime(tmp_path)
    runtime.save_config(VideoConfig(offload_to_cpu=False), "missing")
    tool = VideoGenerationTool(str(tmp_path))
    result = tool.execute(action="status")
    assert result.status == ToolResultStatus.SUCCESS
    assert json.loads(result.content)["config"]["offload_to_cpu"] is False
    assert json.loads(result.content)["model"] == "MiniMax H3"


@pytest.mark.parametrize("args", [
    {"action": "generate", "prompt": "sphere", "width": 17},
    {"action": "job", "job_id": "../../other"},
    {"action": "cancel"},
    {"action": "shell", "prompt": "anything"},
    {"action": "status", "model": "other"},
    {"action": "generate", "prompt": "sphere", "command": "anything"},
])
def test_invalid_request_never_starts_backend(tmp_path, monkeypatch, args):
    tool = VideoGenerationTool(str(tmp_path))
    def unexpected_start(request):
        pytest.fail("invalid input started a backend")
    monkeypatch.setattr(tool.runtime, "start", unexpected_start)
    assert tool.execute(**args).status == ToolResultStatus.FAILURE


def test_generation_returns_async_id_and_same_web_job(tmp_path, monkeypatch):
    tool = VideoGenerationTool(str(tmp_path))
    seen = []
    def start(request):
        seen.append(request)
        return {"id": "a" * 32, "status": "queued"}
    monkeypatch.setattr(tool.runtime, "start", start)
    result = json.loads(tool.execute(action="generate", prompt="sphere", seed=11).content)
    assert seen[0].steps == 8
    assert result["job_id"] == "a" * 32
    assert "output_url" not in result
    monkeypatch.setattr(tool.runtime, "job", lambda job_id: {"id": job_id, "status": "done"})
    done = json.loads(tool.execute(action="job", job_id=result["job_id"]).content)
    assert done["output_url"] == f"/api/v1/video/jobs/{result['job_id']}/files/output"
