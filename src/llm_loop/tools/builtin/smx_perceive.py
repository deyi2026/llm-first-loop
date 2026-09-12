"""基础工具: smx_perceive — smx 感知层 opt-in 并入 LFL 工具面（EVO-20260912-10818cb5）.

并入形态（演进建议锁定）:
  1. wait 条件谓词轮询: file_exists/file_gone/file_contains/port_open（仅 loopback），
     经子进程调用冻结实现 tools/smx/smx.py（不引 shell、不接收命令字符串）。
  2. snapshot/diff: 命令前后目录树快照与净变更（导入 smx.take_snapshot/diff_pair 复用冻结逻辑）。
  3. receipt: 回执摘要查询（摘要字段为主；full=true 给全量 JSON）。

显式不并入: 执行面（exec/bg/collect）→ 维持经 execute_command 硬安全边界；
show 回放 → 不并入（对照实验 0 采用）。本工具是纯感知层: 只读观察 + 本仓 data 目录写快照。

安全约束（与 smx 冻结版一致，胶水层再校验一道）:
  - host 仅 loopback 白名单 {127.0.0.1, ::1, localhost}（smx 内部亦有 S2 拒绝，双层防御）。
  - run_id 白名单 [A-Za-z0-9_.-]（拒 `/` `\\` 与 `..` 片段），防回执查询路径穿越。
  - 任何参数不透传为 shell 命令；subprocess 全部 argv 列表。
opt-in: config.smx_perceive_path 为空 → 工具不注册（默认关闭）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
_RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_SNAP_ID_RE = re.compile(r"snap-[0-9TZ:.-]+-[0-9a-f]{6}")


def _clamp(v: Any, lo: float, hi: float, dflt: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = dflt
    return max(lo, min(hi, x))


class SmxPerceiveTool:
    name = "smx_perceive"
    description = (
        "smx 感知层工具（opt-in，默认不注册；仅感知不执行）。四动作: "
        "wait=条件谓词离散轮询（file_exists/file_gone/file_contains/port_open，仅 loopback）；"
        "satisfied=true/false/null 分别表示满足/有效采样至超时未满足/观察错误或覆盖不足而不可判，"
        "回执给 interval/sample_count/observer_error_count，false 不证明采样间隙从未瞬时成立；"
        "snapshot=目录树快照落盘返回 snap_id、capture-time scope 与独立 content_sha256；"
        "diff=先机械校验 scope comparability；可比但 observation 不完整时 created/deleted=null，"
        "modified 仅保留 observed lower-bound 并用 field_completeness 标明非全集；"
        "wait/snapshot/diff 兼容旧字段并附 nested smc canonical projection；"
        "receipt=按 run_id 查 raw smx 回执，full/raw 均明确 canonical=false 且不伪造 smc。"
        "何时用: 后台命令启动后等待完成标志/端口就绪（替代 sleep+重读）、命令前后净变更取证、查询 smx 回执。"
        "执行动作（跑命令）一律走 execute_command，本工具不执行任何命令。"
        "局限: wait 谓词同一调用仅一个；快照受 depth/budget 截断（回执如实标注）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["wait", "snapshot", "diff", "receipt"],
                "description": "wait=谓词轮询等待；snapshot=目录快照；diff=净变更比对；receipt=回执查询",
            },
            "file_exists": {"type": "string", "description": "wait: 等待该路径存在"},
            "file_gone": {"type": "string", "description": "wait: 等待该路径消失"},
            "file_contains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "wait: [PATH, TEXT] 等待文件包含文本",
            },
            "port_open": {"type": "integer", "description": "wait: 等待本机端口可连（仅 loopback）"},
            "host": {"type": "string", "description": "port_open 目标主机，默认 127.0.0.1，仅允许 loopback"},
            "timeout": {"type": "number", "description": "wait 超时秒（默认 10，钳制到工具窗口）"},
            "interval": {"type": "number", "description": "wait 轮询间隔秒（默认 0.3）"},
            "root": {"type": "string", "description": "wait/receipt: 回执落点根目录（默认当前工作目录）"},
            "roots": {"type": "array", "items": {"type": "string"}, "description": "snapshot: 快照根路径列表（默认当前目录）"},
            "depth": {"type": "integer", "description": "snapshot: 遍历深度（默认 2，钳 1..6）"},
            "budget": {"type": "integer", "description": "snapshot: 条目预算（默认 5000，钳 100..20000）"},
            "since": {"type": "string", "description": "diff: 基线 snapshot_id"},
            "current": {"type": "string", "description": "diff: 第二快照 id（缺省=按基线参数现拍）"},
            "run_id": {"type": "string", "description": "receipt: 回执 run_id（白名单字符）"},
            "full": {"type": "boolean", "description": "receipt: true=返回全量回执 JSON（默认摘要）"},
        },
        "required": ["action"],
    }

    def __init__(self, smx_path: str, data_dir: str, max_wait_s: float = 55.0):
        self._smx_path = str(Path(smx_path).expanduser().resolve())
        self._store = Path(data_dir).expanduser() / "smx_perceive"
        self._max_wait_s = float(max_wait_s)
        self._mod: Any = None
        self._smx_sha: str = ""

    # ---------- 内部 ----------
    def _fail(self, msg: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE, content=msg, tool_call_id="", tool_name=self.name
        )

    def _ok(self, payload: dict) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
            tool_call_id="",
            tool_name=self.name,
        )

    def _load_smx(self) -> Any:
        if self._mod is None:
            p = Path(self._smx_path)
            if not p.is_file():
                raise FileNotFoundError(f"smx 实现不存在: {p}")
            self._smx_sha = hashlib.sha256(p.read_bytes()).hexdigest()[:8]
            spec = importlib.util.spec_from_file_location("lfl_smx_glue", p)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法为冻结实现创建模块 spec: {p}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # 模块级仅常量与函数定义，无副作用
            self._mod = mod
        return self._mod

    @staticmethod
    def _snapshot_content_sha256(doc: dict) -> str:
        """Hash captured snapshot content, excluding random identity and the token itself."""
        basis = {
            key: value
            for key, value in doc.items()
            if key not in {"snapshot_id", "content_sha256"}
        }
        blob = json.dumps(
            basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _load_snap(self, snap_id: str) -> dict:
        sid = str(snap_id or "").strip()
        if not _SNAP_ID_RE.fullmatch(sid):
            raise ValueError(f"snapshot_id 非法: {sid!r}（格式 snap-<ts>-<hex6>）")
        p = self._store / f"{sid}.json"
        if not p.is_file():
            raise FileNotFoundError(f"快照不存在: {p}")
        doc = json.loads(p.read_text(encoding="utf-8"))
        if doc.get("snapshot_id") != sid:
            raise ValueError(
                f"snapshot integrity mismatch: requested={sid!r} stored={doc.get('snapshot_id')!r}"
            )
        token = doc.get("content_sha256")
        if token is not None:
            if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
                raise ValueError(f"snapshot integrity token invalid: {sid}")
            actual = self._snapshot_content_sha256(doc)
            if actual != token:
                raise ValueError(
                    f"snapshot integrity mismatch: {sid} expected={token} actual={actual}"
                )
        return doc

    @staticmethod
    def _snapshot_scope(doc: dict) -> dict | None:
        """Return capture-time mechanical scope identity, never task relevance."""
        scope = doc.get("scope")
        if isinstance(scope, dict):
            roots = scope.get("roots")
            depth = scope.get("depth")
            if (isinstance(roots, list) and roots
                    and all(isinstance(x, str) and x for x in roots)
                    and isinstance(depth, (int, str)) and not isinstance(depth, bool)):
                try:
                    return {"roots": sorted(roots), "depth": int(depth)}
                except ValueError:
                    return None
        # Backward compatibility is safe only for absolute stored roots. Relative roots
        # cannot be re-resolved under a later cwd without silently changing scope.
        params = doc.get("params") or {}
        roots = params.get("roots")
        depth = params.get("depth")
        if (isinstance(roots, list) and roots
                and all(isinstance(x, str) and x and Path(x).is_absolute() for x in roots)
                and isinstance(depth, (int, str)) and not isinstance(depth, bool)):
            try:
                return {
                    "roots": sorted(str(Path(x).resolve(strict=False)) for x in roots),
                    "depth": int(depth),
                }
            except (ValueError, OSError):
                return None
        return None

    @classmethod
    def _scope_relation(cls, base: dict, current: dict) -> tuple[bool, str]:
        left = cls._snapshot_scope(base)
        right = cls._snapshot_scope(current)
        if left is None or right is None:
            return False, "unknown_scope"
        roots_same = left["roots"] == right["roots"]
        depth_same = left["depth"] == right["depth"]
        if roots_same and depth_same:
            return True, "same_scope"
        if not roots_same and not depth_same:
            return False, "different_roots_and_depth"
        if not roots_same:
            return False, "different_roots"
        return False, "different_depth"

    @staticmethod
    def _smc_scope_ref(scope: dict) -> str:
        blob = json.dumps(
            scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"shell-scope:sha256:{hashlib.sha256(blob).hexdigest()}"

    @staticmethod
    def _snapshot_completeness(meta: list[dict]) -> dict:
        reasons: list[str] = []
        for item in meta:
            label = str(item.get("id") or item.get("root") or "root")
            if item.get("truncated"):
                reasons.append(f"{label}:truncated")
            note = item.get("note")
            # not_found is itself a complete mechanical observation of that root.
            if note and note != "not_found":
                reasons.append(f"{label}:{note}")
            for error in item.get("walk_errors") or []:
                reasons.append(f"{label}:walk_error:{error}")
        return {"complete": not reasons, "reasons": reasons}

    @classmethod
    def _smc_world_snapshot(cls, doc: dict, store_path: str) -> dict:
        scope = cls._snapshot_scope(doc) or {"roots": [], "depth": None}
        params = doc.get("params") or {}
        entries = doc.get("entries") or {}
        meta = doc.get("meta") or []
        return {
            "schema": "smc.world_snapshot.v0.1",
            "domain": "shell",
            "snapshot_id": doc.get("snapshot_id"),
            "scope": {
                "roots": list(scope.get("roots") or []),
                "depth": scope.get("depth"),
                "filters": [],
            },
            "observed_at": doc.get("at"),
            "completeness": cls._snapshot_completeness(meta),
            "budget": {
                "entries": len(entries),
                "budget_cap": params.get("budget"),
                "est_tokens": None,
            },
            "grounding_version": doc.get("content_sha256"),
            "projection": {
                "representation": "overview",
                "complete": False,
                "full_ref": store_path,
            },
            "objects_ref": store_path,
            "objects_representation": "raw_fs_entries_v1",
        }

    @staticmethod
    def _canonical_scope_relation(raw_relation: str) -> str:
        if raw_relation == "same_scope":
            return "same"
        if raw_relation == "unknown_scope":
            return "unknown"
        return "changed"

    @classmethod
    def _live_observation_version(cls, entries: dict, meta: list[dict], scope_doc: dict) -> str:
        basis = {
            "entries": entries,
            "meta": meta,
            "scope": cls._snapshot_scope(scope_doc),
        }
        blob = json.dumps(
            basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"live-sha256:{hashlib.sha256(blob).hexdigest()}"

    @classmethod
    def _smc_diff_projection(
        cls,
        *,
        base: dict,
        current_version: str,
        diff: dict | None,
        comparable: bool,
        raw_scope_relation: str,
        base_meta: list[dict],
        current_meta: list[dict],
    ) -> dict:
        base_complete = cls._snapshot_completeness(base_meta)
        current_complete = cls._snapshot_completeness(current_meta)
        reasons = [f"from:{r}" for r in base_complete["reasons"]]
        reasons.extend(f"to:{r}" for r in current_complete["reasons"])
        if not comparable:
            reasons.append(f"scope_incomparable:{raw_scope_relation}")
        observation_complete = (
            comparable and base_complete["complete"] and current_complete["complete"]
        )
        return {
            "schema": "smc.semantic_diff.v0.1",
            "domain": "shell",
            "from_version": base.get("snapshot_id"),
            "to_version": current_version,
            "diff_semantics": "snapshot_pair_net",
            "comparable": comparable,
            "scope_relation": cls._canonical_scope_relation(raw_scope_relation),
            "adapter_scope_relation": raw_scope_relation,
            "created": list(diff["created"]) if observation_complete and diff is not None else None,
            "removed": list(diff["deleted"]) if observation_complete and diff is not None else None,
            "changed": list(diff["modified"]) if comparable and diff is not None else None,
            "completeness": {"complete": observation_complete, "reasons": reasons},
            "field_completeness": {
                "created": observation_complete,
                "removed": observation_complete,
                "changed": observation_complete,
            },
        }

    @classmethod
    def _smc_wait_projection(cls, kw: dict, pred: str, rcp: dict, root: str) -> dict:
        if pred == "port_open":
            host = str(kw.get("host") or "127.0.0.1").strip() or "127.0.0.1"
            port = int(kw["port_open"])
            target = f"tcp://{host}:{port}"
            scope_basis = {"kind": "loopback_tcp", "host": host}
            property_name = "connectable"
            operator = "eq"
            value: Any = True
            operation_class = "probe"
        else:
            raw_target = (
                str(kw["file_contains"][0]) if pred == "file_contains" else str(kw[pred])
            )
            target = str(Path(raw_target).expanduser().resolve(strict=False))
            scope_basis = {"kind": "filesystem", "root": str(Path(target).parent)}
            operation_class = "observe"
            if pred == "file_exists":
                property_name, operator, value = "exists", "eq", True
            elif pred == "file_gone":
                property_name, operator, value = "exists", "eq", False
            else:
                property_name, operator, value = "content_contains", "contains", str(kw["file_contains"][1])
        scope_ref = cls._smc_scope_ref(scope_basis)
        predicate = {
            "schema": "smc.predicate.v0.1",
            "domain": "shell",
            "scope_ref": scope_ref,
            "target": target,
            "property": property_name,
            "operator": operator,
            "value": value,
        }
        predicate_result = dict(rcp.get("predicate_result") or {})
        result = predicate_result.get("result")
        completeness_reasons: list[str] = []
        if result == "indeterminate":
            completeness_reasons.append("predicate_indeterminate")
            if predicate_result.get("observer_error_count"):
                completeness_reasons.append("predicate_observer_error")
            if predicate_result.get("coverage_complete") is False:
                completeness_reasons.append("predicate_coverage_incomplete")
        root_path = Path(root).expanduser().resolve(strict=False) if root else Path.cwd().resolve(strict=False)
        run_id = str(rcp.get("run_id") or "")
        raw_receipt = root_path / ".smx" / "runs" / run_id / "receipt.json"
        if not raw_receipt.is_file():
            completeness_reasons.append("raw_grounding_unavailable")
        return {
            "schema": "smc.action_receipt.v0.1",
            "domain": "shell",
            "scope_ref": scope_ref,
            "action_id": f"act-wait-{run_id}",
            "receipt_id": f"rcp-wait-{run_id}-0001",
            "receipt_seq": 1,
            "verb": "wait",
            "operation_class": operation_class,
            "idempotency_class": "repeatable_observation",
            "atomicity_class": "polling_series",
            "target_id": scope_ref,
            "status": "ok",
            "before_version": None,
            "after_version": None,
            "version_precondition": {
                "status": "not_applicable",
                "reason": "wait_predicate_observation",
            },
            "observed_effects": {},
            "boundary_events": {},
            "grounding_refs": {"raw_receipt": str(raw_receipt)},
            "completeness": {
                "complete": not completeness_reasons,
                "reasons": completeness_reasons,
            },
            "predicate": predicate,
            "predicate_result": predicate_result,
        }

    # ---------- 四动作 ----------
    def _wait(self, kw: dict) -> ToolResult:
        preds = [k for k in ("file_exists", "file_gone", "file_contains", "port_open")
                 if kw.get(k) is not None]
        if len(preds) != 1:
            return self._fail(f"[参数错误] wait 需恰好一个谓词，收到: {preds}")
        self._load_smx()  # 副作用: 校验冻结实现并缓存 _smx_sha（wait 走子进程，不走内存模块）
        argv: list[str] = [sys.executable, self._smx_path, "wait", "--json"]
        pred = preds[0]
        if pred == "file_contains":
            fc = kw.get("file_contains")
            if not (isinstance(fc, (list, tuple)) and len(fc) == 2
                    and all(isinstance(x, str) and x for x in fc)):
                return self._fail("[参数错误] file_contains 须为 [PATH, TEXT] 二元组")
            argv += ["--file-contains", fc[0], fc[1]]
        elif pred == "port_open":
            raw_port = kw.get("port_open")
            if raw_port is None or isinstance(raw_port, bool) or not isinstance(raw_port, (int, str)):
                return self._fail("[参数错误] port_open 须为整数端口")
            try:
                port = int(raw_port)
            except ValueError:
                return self._fail("[参数错误] port_open 须为整数端口")
            if not 1 <= port <= 65535:
                return self._fail("[参数错误] port_open 越界（1..65535）")
            host = str(kw.get("host") or "127.0.0.1").strip() or "127.0.0.1"
            if host not in _LOOPBACK_HOSTS:
                return self._fail(f"[安全拒绝] port_open 仅允许 loopback {sorted(_LOOPBACK_HOSTS)}，收到: {host}")
            argv += ["--port-open", str(port), "--host", host]
        else:
            argv += [f"--{pred.replace('_', '-')}", str(kw.get(pred))]
        timeout = _clamp(kw.get("timeout"), 0.5, self._max_wait_s, 10.0)
        interval = _clamp(kw.get("interval"), 0.1, 5.0, 0.3)
        argv += ["--timeout", f"{timeout:g}", "--interval", f"{interval:g}"]
        root = str(kw.get("root") or "").strip()
        if root:
            argv += ["--root", root]
        try:
            cp = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout + 15.0)
        except subprocess.TimeoutExpired:
            return self._fail(f"[wait 异常] 子进程超预算未返回（timeout={timeout:g}s），谓词未收敛，回执可能未落盘")
        out = (cp.stdout or "").strip()
        rcp: dict | None = None
        if out:
            # smx 回执为多行缩进 JSON：整体解析；失败再兜底首'{'到末'}'切片（防警告行混入）
            for candidate in (out, out[out.find("{"): out.rfind("}") + 1]):
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        rcp = parsed
                        break
                except json.JSONDecodeError:
                    continue
        if rcp is None:
            return self._fail(
                f"[wait 异常] 未取到 JSON 回执（exit={cp.returncode}）stderr: "
                f"{(cp.stderr or '').strip()[:300]}"
            )
        rcp["_smx_sha"] = self._smx_sha
        rcp["smc"] = self._smc_wait_projection(kw, pred, rcp, root)
        # exit 2 = 谓词超时未满足，属正常观测结果而非工具故障
        return self._ok(rcp)

    def _snapshot(self, kw: dict) -> ToolResult:
        mod = self._load_smx()
        roots_in = kw.get("roots") or []
        if not isinstance(roots_in, (list, tuple)) or not all(isinstance(r, str) and r for r in roots_in):
            return self._fail("[参数错误] roots 须为非空字符串列表（缺省=当前目录）")
        roots = [
            str(Path(r).expanduser().resolve(strict=False)) for r in roots_in
        ] or [str(Path.cwd().resolve(strict=False))]
        depth = int(_clamp(kw.get("depth"), 1, 6, 2))
        budget = int(_clamp(kw.get("budget"), 100, 20000, 5000))
        entries, meta = mod.take_snapshot(
            [(f"r{i}", p) for i, p in enumerate(roots)], depth, budget
        )
        self._store.mkdir(parents=True, exist_ok=True)
        sid = f"snap-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"
        doc = {
            "schema": 1,
            "tool": "smx_perceive",
            "snapshot_id": sid,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "smx_sha": self._smx_sha,
            "params": {"roots": roots, "depth": depth, "budget": budget},
            "scope": {"roots": sorted(roots), "depth": depth},
            "meta": meta,
            "entries": entries,
            "content_sha256_basis": "canonical_snapshot_content_v1",
        }
        doc["content_sha256"] = self._snapshot_content_sha256(doc)
        store_path = self._store / f"{sid}.json"
        store_path.write_text(
            json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        payload = {
            "action": "snapshot",
            "snapshot_id": sid,
            "entries": len(entries),
            "roots_meta": meta,
            "scope": doc["scope"],
            "content_sha256": doc["content_sha256"],
            "content_sha256_basis": doc["content_sha256_basis"],
            "store_path": str(store_path),
            "smx_sha": self._smx_sha,
        }
        payload["smc"] = self._smc_world_snapshot(doc, str(store_path))
        return self._ok(payload)

    def _diff(self, kw: dict) -> ToolResult:
        mod = self._load_smx()
        since = str(kw.get("since") or "").strip()
        if not since:
            return self._fail("[参数错误] diff 需要基线 snapshot_id（since）")
        try:
            base = self._load_snap(since)
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
            return self._fail(f"[diff 基线不可用] {e}")
        cur_id = str(kw.get("current") or "").strip()
        if cur_id:
            try:
                cur = self._load_snap(cur_id)
            except (ValueError, FileNotFoundError, json.JSONDecodeError) as e:
                return self._fail(f"[diff 对端不可用] {e}")
            after_entries = cur.get("entries", {})
            after_meta = cur.get("meta", [])
            scope_note = f"snapshot:{cur_id}"
            current_version = cur_id
        else:
            prm = base.get("params", {})
            roots = prm.get("roots") or [str(Path.cwd())]
            depth = int(prm.get("depth", 2) or 2)
            budget = int(prm.get("budget", 5000) or 5000)
            after_entries, after_meta = mod.take_snapshot(
                [(f"r{i}", p) for i, p in enumerate(roots)], depth, budget
            )
            cur = {
                "params": {"roots": roots, "depth": depth, "budget": budget},
                "scope": base.get("scope") or self._snapshot_scope(base),
            }
            scope_note = "live(按基线参数现拍)"
            current_version = self._live_observation_version(after_entries, after_meta, cur)
        base_meta = base.get("meta", [])
        comparable, scope_relation = self._scope_relation(base, cur)
        if not comparable:
            payload = {
                "action": "diff",
                "baseline": base.get("snapshot_id"),
                "current": scope_note,
                "comparable": False,
                "scope_relation": scope_relation,
                "created": None,
                "deleted": None,
                "modified": None,
                "field_completeness": {
                    "created": False,
                    "deleted": False,
                    "modified": False,
                    "total_changes": False,
                },
                "modified_semantics": "unknown_incomparable_scope",
                "diff_complete": False,
                "meta": {"baseline": base_meta, "current": after_meta},
                "display_rows": [],
                "display_truncated": False,
                "total_changes": None,
                "smx_sha": self._smx_sha,
                "warning": (
                    "两次 observation scope 不可机械比较；未生成 created/deleted/modified。"
                    "由模型决定是否以同一 scope 重新观察。"
                ),
            }
            payload["smc"] = self._smc_diff_projection(
                base=base,
                current_version=current_version,
                diff=None,
                comparable=False,
                raw_scope_relation=scope_relation,
                base_meta=base_meta,
                current_meta=after_meta,
            )
            return self._ok(payload)
        d = mod.diff_pair(base.get("entries", {}), after_entries)
        rows, truncated, total = mod.changed_display(d, base.get("params", {}).get("roots", ["."])[0], cap=40)
        # 完整性纪律(P1): 任一侧截断/遍历异常时，±差集可能只是 budget 裁剪伪影，
        # 不得当作 created/deleted 报告 → 计数降级为 null(unknown) 并抑制 ± 显示行。
        incomplete = not (
            self._snapshot_completeness(base_meta)["complete"]
            and self._snapshot_completeness(after_meta)["complete"]
        )
        if incomplete:
            rows = [r for r in rows if not r.startswith(("+", "-"))]
        payload = {
            "action": "diff",
            "baseline": base.get("snapshot_id"),
            "current": scope_note,
            "comparable": True,
            "scope_relation": scope_relation,
            "created": None if incomplete else len(d["created"]),
            "deleted": None if incomplete else len(d["deleted"]),
            "modified": len(d["modified"]),
            "field_completeness": {
                "created": not incomplete,
                "deleted": not incomplete,
                "modified": not incomplete,
                "total_changes": not incomplete,
            },
            "modified_semantics": "observed_lower_bound" if incomplete else "complete",
            "diff_complete": not incomplete,
            "meta": {"baseline": base_meta, "current": after_meta},
            "display_rows": rows,
            "display_truncated": truncated,
            "total_changes": None if incomplete else total,
            "smx_sha": self._smx_sha,
        }
        payload["smc"] = self._smc_diff_projection(
            base=base,
            current_version=current_version,
            diff=d,
            comparable=True,
            raw_scope_relation=scope_relation,
            base_meta=base_meta,
            current_meta=after_meta,
        )
        if incomplete:
            payload["warning"] = (
                "快照不完整（budget 截断或遍历异常）：created/deleted 不可判，已置 null 并抑制 ± 行；"
                "modified 仅为已观察交集中的真实 lower-bound，不保证 exhaustive。"
                "是否增大 budget 重拍由模型决定"
            )
        return self._ok(payload)

    def _receipt(self, kw: dict) -> ToolResult:
        rid = str(kw.get("run_id") or "").strip()
        if not _RUN_ID_RE.fullmatch(rid):
            return self._fail(f"[安全拒绝] run_id 非法（白名单 [A-Za-z0-9_.-]，拒 / \\ 与 .. 片段）: {rid!r}")
        root = str(kw.get("root") or "").strip()
        root_p = Path(root).expanduser() if root else Path.cwd()
        p = root_p / ".smx" / "runs" / rid / "receipt.json"
        if not p.is_file():
            return self._fail(f"[回执不存在] {p}（root 应为 smx 运行时 --root/cwd）")
        try:
            rcp = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return self._fail(f"[回执读取失败] {p}: {e}")
        if bool(kw.get("full")):
            # Raw CLI receipt hydration is evidence, not a canonical SMC projection.
            # Annotate the in-memory response only; never rewrite the stored receipt.
            rcp["canonical"] = False
            rcp["representation"] = "raw_smx_receipt"
            rcp["grounding"] = {
                "kind": "smx_cli_receipt",
                "run_id": rcp.get("run_id", rid),
                "canonical": False,
            }
            raw_diff = rcp.get("diff")
            if isinstance(raw_diff, dict):
                raw_diff["canonical"] = False
                raw_diff["representation"] = "raw_smx_diff"
            rcp["_receipt_path"] = str(p)
            return self._ok(rcp)
        diff = rcp.get("diff") or {}
        summary = {
            "action": "receipt",
            "canonical": False,
            "representation": "raw_smx_receipt_summary",
            "run_id": rcp.get("run_id", rid),
            "kind": rcp.get("kind"),
            "cmd": rcp.get("cmd"),
            "exit": rcp.get("exit"),
            "rc_chain": rcp.get("rc_chain"),
            "satisfied": rcp.get("satisfied"),
            "waited_ms": rcp.get("waited_ms"),
            "detail": rcp.get("detail"),
            "diff_counts": {k: len(v) for k, v in diff.items() if isinstance(v, list)},
            "at": rcp.get("at"),
            "receipt_path": str(p),
            "hint": "full=true 可取 raw 全量；raw receipt/diff 明确 canonical=false",
        }
        return self._ok(summary)

    # ---------- 入口 ----------
    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip()
        try:
            if action == "wait":
                return self._wait(kwargs)
            if action == "snapshot":
                return self._snapshot(kwargs)
            if action == "diff":
                return self._diff(kwargs)
            if action == "receipt":
                return self._receipt(kwargs)
            return self._fail(f"[参数错误] action 须为 wait|snapshot|diff|receipt，收到: {action!r}")
        except (OSError, ValueError) as e:
            return self._fail(f"[smx_perceive:{action}] 失败: {type(e).__name__}: {e}")
