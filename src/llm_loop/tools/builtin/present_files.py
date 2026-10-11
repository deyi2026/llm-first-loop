"""输出交付物声明工具（对齐 DSH present 语义）.

模型在给出最终答复前，把"用户要求得到的输出文件"显式声明为交付物；声明
进入消息流后，Web 会话"出产物"面板即可点击打开/预览（复用既有
``/api/v1/files/preview`` 只读管道）。这补上了 execute_command 等方式创建
的文件不会自动进入出产物面板的缺口——edit_file/write_file 有参数级路径
可提取，shell 产物没有。

机械边界（程序所有，语义归模型）：
- 路径必须位于当前工作区根内（相对/绝对均可，resolve 后越界拒绝）；
- 仅接受已存在的普通文件（目录/缺失拒绝）；
- 全有或全无：任一文件无效 → 整体 FAILURE 并逐项给出原因；
- 只登记事实（字节大小/修改时间），不复制、不改内容、不判重要性。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import workspace_base

_MAX_FILES = 20


class PresentFilesTool:
    name = "present_files"
    description = (
        "把已存在的输出文件声明为最终交付物（对齐 DSH present 语义）——声明后用户在 Web 会话"
        "的出产物面板可直接点击打开/预览该文件。"
        "何时用: 用户要求得到的产出（报告/方案/导出数据/构建产物/文档等）在写入完成之后、"
        "给出最终答复之前声明；execute_command 重定向等方式创建的文件尤其必须显式声明"
        "（它们不会自动进入出产物面板）。"
        "何时不用: 中间过程文件、尚未定稿仍在迭代的内容、目录或不存在的路径（机械拒绝）。"
        "边界: 路径须在当前工作区根内（相对/绝对均可，越界拒绝）；只登记大小/修改时间事实，"
        "不复制不改内容；每次至多 20 个文件，全有或全无。"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "文件路径（相对工作区根或绝对路径）"},
                        "description": {
                            "type": "string",
                            "description": "一句话说明该交付物（展示于出产物面板 tooltip）",
                        },
                    },
                    "required": ["path"],
                },
                "minItems": 1,
                "maxItems": 20,
                "description": "待声明的交付物文件列表",
            },
        },
        "required": ["files"],
    }

    def execute(self, **kwargs) -> ToolResult:
        return self._run(kwargs)

    def _run(self, arguments: dict) -> ToolResult:
        files = arguments.get("files")
        if not isinstance(files, list) or not files:
            return self._fail("缺少必填参数 'files'（非空数组，元素为 {path, description?}）")
        if len(files) > _MAX_FILES:
            return self._fail(f"单次至多声明 {_MAX_FILES} 个文件（收到 {len(files)} 个）")


        base = Path(workspace_base()).resolve()
        facts: list[dict[str, Any]] = []
        for idx, item in enumerate(files):
            if not isinstance(item, dict):
                return self._fail(f"files[{idx}] 必须是对象（收到 {type(item).__name__}）")
            raw_path = str(item.get("path", "") or "").strip()
            if not raw_path:
                return self._fail(f"files[{idx}] 缺少非空 'path'")
            raw = Path(raw_path)
            target = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
            if not target.is_relative_to(base):
                return self._fail(
                    f"路径越出工作区根，已拒绝: {raw_path}（根={base}）"
                )
            if not target.exists():
                return self._fail(f"文件不存在: {raw_path}")
            if not target.is_file():
                return self._fail(f"仅接受普通文件（收到目录或其他类型）: {raw_path}")
            stat = target.stat()
            facts.append(
                {
                    "path": raw_path,
                    "description": str(item.get("description", "") or "").strip(),
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )

        lines = [
            "[present_files] "
            f"已声明 {len(facts)} 个交付物（用户可在 Web 会话出产物面板打开/预览）："
        ]
        for f in facts:
            note = f" — {f['description']}" if f["description"] else ""
            lines.append(f"- {f['path']} ({f['size']}B, {f['mtime']}){note}")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[present_files] {content}",
            tool_call_id="",
            tool_name=self.name,
        )
