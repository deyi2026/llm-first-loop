"""示例 01：最小 CLI 循环（5 行接入）.

把 LLM-First Core Loop 嵌入自有脚本的最短路径：
装配引擎 → 建会话 → run → 拿结果。

运行: LLM_API_KEY=sk-xxx LLM_BASE_URL=https://api.deepseek.com/v1 python examples/01_minimal_cli_loop.py
"""

from __future__ import annotations

from llm_loop.config import load_env_file, load_settings
from llm_loop.factory import build_engine


def main() -> None:
    load_env_file()  # 读取项目根 .env（已设置的环境变量优先）
    engine = build_engine(load_settings())

    sid = engine.session.create()
    result = engine.run(sid, "请读取 data/notes.txt 并总结内容")
    print("=" * 40)
    print(result.final_answer)
    print("=" * 40)
    print(f"[元信息] 模型: {result.model_used} | 轮数: {result.rounds} | "
          f"工具调用: {len(result.tool_calls)} 次 | 截断: {result.truncated}")


if __name__ == "__main__":
    main()
