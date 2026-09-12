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
        "wait=条件谓词轮询（file_exists/file_gone/file_contains/port_open，仅 loopback，满足即返回回执，"
        "超时返回 satisfied=false 不算失败）；snapshot=目录树快照落盘返回 snap_id；"
        "diff=快照 vs 当前（或两个快照）净变更；receipt=按 run_id 查 smx 回执摘要。"
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
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # 模块级仅常量与函数定义，无副作用
            self._mod = mod
        return self._mod

    def _load_snap(self, snap_id: str) -> dict:
        sid = str(snap_id or "").strip()
        if not _SNAP_ID_RE.fullmatch(sid):
            raise ValueError(f"snapshot_id 非法: {sid!r}（格式 snap-<ts>-<hex6>）")
        p = self._store / f"{sid}.json"
        if not p.is_file():
            raise FileNotFoundError(f"快照不存在: {p}")
        return json.loads(p.read_text(encoding="utf-8"))

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
            try:
                port = int(kw.get("port_open"))
            except (TypeError, ValueError):
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
        # exit 2 = 谓词超时未满足，属正常观测结果而非工具故障
        return self._ok(rcp)

    def _snapshot(self, kw: dict) -> ToolResult:
        mod = self._load_smx()
        roots_in = kw.get("roots") or []
        if not isinstance(roots_in, (list, tuple)) or not all(isinstance(r, str) and r for r in roots_in):
            return self._fail("[参数错误] roots 须为非空字符串列表（缺省=当前目录）")
        roots = [str(Path(r).expanduser()) for r in roots_in] or [str(Path.cwd())]
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
            "meta": meta,
            "entries": entries,
        }
        (self._store / f"{sid}.json").write_text(
            json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        return self._ok({
            "action": "snapshot",
            "snapshot_id": sid,
            "entries": len(entries),
            "roots_meta": meta,
            "store_path": str(self._store / f"{sid}.json"),
            "smx_sha": self._smx_sha,
        })

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
        else:
            prm = base.get("params", {})
            roots = prm.get("roots") or [str(Path.cwd())]
            depth = int(prm.get("depth", 2) or 2)
            budget = int(prm.get("budget", 5000) or 5000)
            after_entries, after_meta = mod.take_snapshot(
                [(f"r{i}", p) for i, p in enumerate(roots)], depth, budget
            )
            scope_note = "live(按基线参数现拍)"
        base_meta = base.get("meta", [])
        d = mod.diff_pair(base.get("entries", {}), after_entries)
        rows, truncated, total = mod.changed_display(d, base.get("params", {}).get("roots", ["."])[0], cap=40)
        # 完整性纪律(P1): 任一侧截断/遍历异常时，±差集可能只是 budget 裁剪伪影，
        # 不得当作 created/deleted 报告 → 计数降级为 null(unknown) 并抑制 ± 显示行。
        incomplete = any(m.get("truncated") or m.get("note") for m in base_meta + after_meta)
        if incomplete:
            rows = [r for r in rows if not r.startswith(("+", "-"))]
        payload = {
            "action": "diff",
            "baseline": base.get("snapshot_id"),
            "current": scope_note,
            "created": None if incomplete else len(d["created"]),
            "deleted": None if incomplete else len(d["deleted"]),
            "modified": len(d["modified"]),
            "diff_complete": not incomplete,
            "meta": {"baseline": base_meta, "current": after_meta},
            "display_rows": rows,
            "display_truncated": truncated,
            "total_changes": None if incomplete else total,
            "smx_sha": self._smx_sha,
        }
        if incomplete:
            payload["warning"] = ("快照不完整（budget 截断或遍历异常）：created/deleted 不可判，"
                                  "已置 null 并抑制 ± 行；请增大 budget 后重拍重比")
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
            rcp["_receipt_path"] = str(p)
            return self._ok(rcp)
        diff = rcp.get("diff") or {}
        summary = {
            "action": "receipt",
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
            "hint": "full=true 可取全量",
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
