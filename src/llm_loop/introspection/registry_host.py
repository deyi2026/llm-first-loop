"""工具注册拆分共享宿主协议（T2，design §2.1.2-5.2）.

各 registry_*.py 模块经 RegistryHost 协议访问 CorrectionToolRegistry 的
注入通道与审计方法，避免循环导入（运行时 host 为 CorrectionToolRegistry 实例）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from llm_loop.introspection.corrections import CorrectionContext


class RegistryHost(Protocol):
    """各 registry 模块访问宿主注册表的协议（结构子类型）."""

    @property
    def ctx(self) -> CorrectionContext: ...

    @property
    def audit_dir(self) -> Path | None: ...

    @property
    def status_provider(self) -> Any: ...

    @property
    def archive_store(self) -> Any: ...

    @property
    def search_records_fn(self) -> Any: ...

    @property
    def search_docs_fn(self) -> Any: ...

    @property
    def experience_store(self) -> Any: ...

    @property
    def recovery_channel(self) -> Any: ...

    @property
    def recovery_sessions_dir(self) -> str | Path | None: ...

    @property
    def recovery_memory_dir(self) -> str | Path | None: ...

    @property
    def skills_dir(self) -> str | None: ...  # B3: 插件化 Skill 目录（未注入 None → 空清单）

    def audit(self, tool_name: str, arguments: dict, result_status: str) -> None: ...

    def current_session_id(self) -> str: ...

    def current_params(self) -> dict: ...
