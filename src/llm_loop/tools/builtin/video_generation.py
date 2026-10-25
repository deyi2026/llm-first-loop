"""Agent adapter for the same durable H3 runtime used by the Web panel."""

from __future__ import annotations

import json

from pydantic import ValidationError

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.video.runtime import VideoError, VideoRequest, VideoRuntime


class VideoGenerationTool:
    name = "video_generation"
    description = (
        "使用 MiniMax H3 生成带原生音频的本地视频。与 Web 的视频模型配置、任务列表和执行槽共用。"
        "status 查看组件就绪情况；generate 提交后台任务并立即返回 job_id；job 查询终态和播放/下载链接；"
        "cancel 取消。生成不阻塞聊天，不自动重试。只接受已通过视频参考图入口上传的 reference IDs。"
        "默认 640×384、56 帧（约 2.3 秒）、8 步；短预览可用 256×256、22 帧、4 步。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "generate", "job", "cancel"]},
            "model": {"type": "string", "enum": ["minimax-h3"]},
            "job_id": {"type": "string"},
            "prompt": {"type": "string", "description": "人物、动作、镜头和声音；参考图用 <Picture 1> 指代"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "frames": {"type": "integer"},
            "steps": {"type": "integer"},
            "seed": {"type": "integer"},
            "references": {"type": "array", "items": {"type": "string"}, "maxItems": 9},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, data_dir: str, *, model_root: str = "", sd_cli: str = ""):
        self.runtime = VideoRuntime(data_dir, model_root=model_root, sd_cli=sd_cli)

    def execute(self, **kwargs) -> ToolResult:
        try:
            result = self._dispatch(kwargs)
        except (VideoError, ValidationError, OSError, ValueError) as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"视频任务未完成：{exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(result, ensure_ascii=False),
            tool_call_id="",
            tool_name=self.name,
        )

    def _dispatch(self, args: dict) -> dict:
        unknown = set(args) - set(self.parameters["properties"])
        if unknown:
            raise ValueError("未知参数：" + ", ".join(sorted(unknown)))
        if args.get("model", "minimax-h3") != "minimax-h3":
            raise ValueError("视频模型只支持 minimax-h3")
        action = args.get("action")
        if action == "status":
            return self.runtime.status()
        if action == "generate":
            request = VideoRequest.model_validate(
                {k: v for k, v in args.items() if k not in {"action", "model", "job_id"}}
            )
            record = self.runtime.start(request)
        elif action in {"job", "cancel"}:
            job_id = args.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise ValueError("job/cancel 必须提供 job_id")
            record = self.runtime.cancel(job_id) if action == "cancel" else self.runtime.job(job_id)
        else:
            raise ValueError("action 必须为 status/generate/job/cancel")
        result = dict(record)
        result["job_id"] = record["id"]
        base = f"/api/v1/video/jobs/{record['id']}"
        result["status_url"] = base
        result["request_url"] = base + "/files/request"
        result["log_url"] = base + "/files/log"
        if record["status"] == "done":
            result["output_url"] = base + "/files/output"
        return result
