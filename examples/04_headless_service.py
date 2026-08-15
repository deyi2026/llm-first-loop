"""示例 04：headless 服务模式（最小 FastAPI 嵌入，无 UI 纯 API）.

演示 B5: 把 LLM-First Core Loop 作为 headless 服务嵌入自有应用——
5 行装配 + 两个端点（同步对话 / 流式对话），无 Web 前端依赖。

运行:
  LLM_API_KEY=sk-xxx LLM_BASE_URL=https://api.deepseek.com/v1 \
  python examples/04_headless_service.py
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine


def build_headless_app() -> FastAPI:
    """headless 装配: 引擎单实例 + 对话端点（同步/流式）."""
    load_env_file()
    engine = build_engine(load_settings())

    app = FastAPI(title="llm-first-loop-headless", version="0.4.0")
    app.state.engine = engine

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "llm-first-loop-headless"}

    @app.post("/chat")
    def chat(body: dict) -> dict:
        """同步对话: {"text": "..."} → {"answer": "...", "rounds": N}"""
        result = engine.run_single(body["text"])
        return {"answer": result.final_answer, "rounds": result.rounds}

    @app.post("/chat/stream")
    def chat_stream(body: dict) -> StreamingResponse:
        """流式对话: SSE 逐段输出（内容增量 + 结束事件带完整结果）."""

        def _gen():
            for delta in engine.run_stream(
                engine.session.create(), body["text"]
            ):
                if delta.content:
                    yield f"data: {delta.content}\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream")

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_headless_app(), host="127.0.0.1", port=8903)
