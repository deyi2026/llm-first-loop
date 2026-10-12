"""CodeArts 子 Agent 调度集成（spec.md / design.md 同目录）.

将华为云 CodeArts 的 Agent 与流水线能力作为可调度子 Agent 纳入
llm-first-loop 任务编排体系。缺省 fail-open 零装配（CODEARTS_ENABLED=false
或缺凭证时本组件不注册调度工具，对现有运行时零影响）。
"""

from __future__ import annotations
