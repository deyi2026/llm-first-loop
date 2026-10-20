"""Model-authored task state and exact recent tool facts; no automatic summaries."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_run_generation, current_session_id, workspace_base
from llm_loop.core.tool_execution_journal import current_effect_mutation_authority


class TaskStateTool:
    name = "task_state"
    description = (
        "保存/读取当前会话中模型自写的任务状态（目标、已核实事实和引用、未执行动作、未决问题）；"
        "程序不生成摘要、不判断任务完成，不自动注入。read 可恢复同会话旧版本并标明run来源；"
        "recent_tools 查询最近精确工具参数指纹及结果引用，重复次数不代表任务进展或禁止重读。"
        "read_manifest 可读取本会话最新压缩来源索引；read_message 按manifest的msg_seq回读完整消息"
        "（含tool_calls/reasoning），字符分页offset单调推进。clear 撤下当前状态。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["save", "read", "clear", "recent_tools", "read_message", "read_manifest"]},
            "state": {"type": "string", "maxLength": 32000},
            "source_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 64},
            "state_ref": {"type": "string", "description": "read: optional exact task-state:<event_id>"},
            "message_index": {"type": "integer", "minimum": 0},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 32000},
            "expected_sha256": {"type": "string"},
            "manifest_sha256": {"type": "string"},

        },
        "required": ["action"],
    }

    def __init__(self, session_store: Any, event_store: Any, *, data_dir: str = "") -> None:
        self.session_store = session_store
        self.event_store = event_store
        self.data_dir = data_dir

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            sid = current_session_id.get()
            if not sid or self.event_store is None or not self.event_store.enabled:
                raise ValueError("current session/event store unavailable")
            # Reuse session ownership validation; callers cannot choose another session.
            session = self.session_store.load(sid)
            events = self.event_store.read_cached(sid)
            action = kwargs.get("action")
            scope = workspace_base()
            generation = current_run_generation.get()
            if action in {"save", "clear"}:
                text = kwargs.get("state", "") if action == "save" else ""
                refs = kwargs.get("source_refs", [])
                if not generation:
                    raise ValueError("active run generation required for state writes")
                if not isinstance(text, str) or len(text) > 32000 or (action == "save" and not text.strip()):
                    raise ValueError("save requires nonempty model-authored state, at most 32000 characters")
                if not isinstance(refs, list) or len(refs) > 64 or any(
                    not isinstance(ref, str) or len(ref) > 512 for ref in refs
                ):
                    raise ValueError("invalid source_refs")
                payload = {
                    "workspace": scope, "run_generation": generation,
                    "state": text, "source_refs": refs, "cleared": action == "clear",
                    "source_seq": events[-1].seq if events else 0,
                    "state_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "author": "model", "semantic_verified": False, "automatic_replay": False,
                }
                with current_effect_mutation_authority() as authority:
                    if not authority:
                        raise ValueError("task state write rejected: stale or cancelled tool attempt")
                    event = self.event_store.append(sid, "task.state.saved", payload)
                if event is None:
                    raise ValueError("task state persistence failed; no state version was saved")
                result = {"state_ref": "task-state:" + event.event_id, **payload}
            elif action == "read":
                wanted = str(kwargs.get("state_ref") or "")
                candidates = [event for event in events if event.type == "task.state.saved"
                              and event.payload.get("workspace") == scope
                              and (not wanted or wanted == "task-state:" + event.event_id)]
                if not candidates:
                    raise ValueError("task state not found in current session/workspace")
                event = candidates[-1]
                payload = event.payload
                if hashlib.sha256(str(payload.get("state", "")).encode()).hexdigest() != payload.get("state_sha256"):
                    raise ValueError("task state source hash mismatch")
                result = {"state_ref": "task-state:" + event.event_id, **payload,
                          "applies_to_current_run": payload.get("run_generation") == generation}
            elif action == "read_manifest":
                wanted = kwargs.get("manifest_sha256")
                choices = [event for event in events if event.type == "compaction.snapshot"
                           and (not wanted or event.payload.get("sha256") == wanted)]
                if not choices or not self.data_dir:
                    raise ValueError("compaction manifest not found in current session")
                record = choices[-1].payload
                root = (Path(self.data_dir) / "compaction_snapshots" / sid).resolve()
                path = (Path(self.data_dir) / str(record.get("path", ""))).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError("manifest outside current session source scope")
                source = path.read_text(encoding="utf-8")
                manifest = json.loads(source)
                if not isinstance(manifest, dict):
                    raise ValueError("compaction manifest must be an object")
                embedded_sha = manifest.pop("sha256", None)
                canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
                sha = hashlib.sha256(canonical.encode()).hexdigest()
                if sha != record.get("sha256") or sha != embedded_sha:
                    raise ValueError("compaction manifest source hash mismatch")
                offset, limit = kwargs.get("offset", 0), kwargs.get("limit", 32000)
                if any(isinstance(v, bool) or not isinstance(v, int) for v in (offset, limit)):
                    raise ValueError("offset/limit must be integers")
                if offset < 0 or not 1 <= limit <= 32000:
                    raise ValueError("manifest range outside resource limit")
                end = min(len(source), offset + limit)
                result = {"manifest_sha256": sha, "source_chars": len(source),
                          "offset": offset, "next_offset": end if end < len(source) else None,
                          "has_more": end < len(source), "text": source[offset:end],
                          "authority": False, "instruction": False}
            elif action == "read_message":
                index = kwargs.get("message_index")
                offset, limit = kwargs.get("offset", 0), kwargs.get("limit", 32000)
                if (not isinstance(index, int) or isinstance(index, bool)
                        or any(isinstance(v, bool) or not isinstance(v, int) for v in (offset, limit))):
                    raise ValueError("message_index/offset/limit must be integers")
                if not 0 <= index < len(session.messages) or offset < 0 or not 1 <= limit <= 32000:
                    raise ValueError("message range outside current session or resource limit")
                source = json.dumps(asdict(session.messages[index]), ensure_ascii=False, sort_keys=True)
                sha = hashlib.sha256(source.encode()).hexdigest()
                if kwargs.get("expected_sha256") and kwargs["expected_sha256"] != sha:
                    raise ValueError("message source changed or was retracted")
                end = min(len(source), offset + limit)
                result = {
                    "source_ref": f"session-message:{sid}:{index}:{sha}",
                    "message_index": index, "source_sha256": sha,
                    "representation": "persisted_message", "source_complete": True,
                    "source_chars": len(source), "offset": offset,
                    "next_offset": end if end < len(source) else None,
                    "has_more": end < len(source), "text": source[offset:end],
                    "authority": False, "instruction": False,
                }
            elif action == "recent_tools":
                declared = [event for event in events if event.type == "tool.execution.declared"][-40:]
                counts = Counter((event.payload.get("tool_name"), event.payload.get("args_sha256"))
                                 for event in declared)
                receipts = {event.payload.get("execution_id"): event.event_id for event in events
                            if event.type == "tool.execution.receipt_committed"}
                results = {event.payload.get("execution_id"): event.payload for event in events
                           if event.type == "tool.execution.finished"}
                result = {
                    "scope": "last_40_declarations", "task_progress": "not_evaluated",
                    "source_versions_equal": "not_evaluated",
                    "calls": [{"event_id": event.event_id, "seq": event.seq, **event.payload,
                               "result": results.get(event.payload.get("execution_id")),
                               "receipt_event_ref": receipts.get(event.payload.get("execution_id")),
                               "same_arguments_in_window": counts[
                                   (event.payload.get("tool_name"), event.payload.get("args_sha256"))]}
                              for event in declared],
                }
            else:
                raise ValueError("unsupported task_state action")
            return ToolResult(ToolResultStatus.SUCCESS, json.dumps(result, ensure_ascii=False),
                              "", self.name)
        except (ValueError, OSError, KeyError) as exc:
            return ToolResult(ToolResultStatus.FAILURE, f"[task state] {exc}", "", self.name)
