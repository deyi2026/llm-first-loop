"""示例 02：Web 嵌入（FastAPI 应用内挂载对话端点）.

build_app 返回完整 FastAPI 应用（鉴权/上传/SSE/会话列表已含）；
也可把 engine 挂到自有 app 上按需暴露端点。

运行: LLM_API_KEY=... LLM_BASE_URL=... python examples/02_web_embed.py
（默认 127.0.0.1:8902，浏览器打开即可对话）
"""

from __future__ import annotations

import uvicorn

from llm_loop.config import load_env_file, load_settings
from llm_loop.web import build_app


def main() -> None:
    load_env_file()
    app = build_app(settings=load_settings())
    uvicorn.run(app, host="127.0.0.1", port=8902, timeout_graceful_shutdown=10)


if __name__ == "__main__":
    main()
