"""L3 协助收件箱：跨会话协助请求的文件式持久化存储（DESIGN-20261105 §4.7 / L3）.

目录约定（与既有 data/interop/dsh_to_lfl、lfl_to_dsh 同构）:
    <data_dir>/interop/session/pending/<id>.json   未决协助请求
    <data_dir>/interop/session/done/<id>.json      已应答（resolved / declined）

消息字段:
    {"id","ts","from_session","to_session","lane_id","goal_id",
     "topic","body","need","deadline","state"}

口径:
- need ∈ {"info","block","review"}；state 初始 "pending"，应答后置 "resolved"/"declined"。
  （S1 第 8 条机检 lane_gate._check_s1_08 以 need=="block" 且 state=="pending" 判定阻塞，
  本存储是该检查的数据源。）
- 每条消息一个独立文件: post 用 tmp + os.replace 原子落盘（与 lane.py 同构），
  id 取 uuid4 保证分片互不冲突，多线程并发 post 不丢消息、无需整账本锁。
- 损坏判定与 LaneStore 不同但同为如实口径: 单文件不可解析只影响该文件自身，
  list_pending/counts 跳过并经 corrupted_count() 如实计数（不静默失败、也不整体拒绝）；
  resolve 遇损坏文件拒绝应答（fail-closed: 无法安全判定就不改）。
- 收到协助请求 ≠ 获得写权（设计 §4.7 权限边界，本模块只做投递/应答记账）。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

HELP_NEEDS = ("info", "block", "review")
HELP_DECISIONS = ("resolved", "declined")  # state 终态（应答结果）

_INBOX_REL = ("interop", "session")  # <data_dir>/interop/session/{pending,done}


class HelpInboxError(RuntimeError):
    """非法输入（topic 为空 / need 或 decision 非法 / 应答损坏文件）。"""


class HelpInboxNotFoundError(HelpInboxError):
    """消息不存在: pending/ 与 done/ 下均无该 id。"""


class HelpInboxCorruptionError(HelpInboxError):
    """消息文件损坏，无法安全应答（resolve fail-closed）。"""


class HelpInbox:
    """文件式协助收件箱: pending/ + done/，一消息一文件（跨会话持久化）."""

    def __init__(self, data_dir: str | Path) -> None:
        base = Path(data_dir).joinpath(*_INBOX_REL)
        self._pending_dir = base / "pending"
        self._done_dir = base / "done"
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        self._done_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 路径 ----------------

    def pending_path(self, msg_id: str) -> Path:
        return self._pending_dir / f"{msg_id}.json"

    def done_path(self, msg_id: str) -> Path:
        return self._done_dir / f"{msg_id}.json"

    # ---------------- 写入 ----------------

    def post(
        self,
        *,
        topic: str,
        body: str = "",
        need: str = "info",
        from_session: str = "",
        to_session: str = "",
        lane_id: str = "",
        goal_id: str = "",
        deadline: str = "",
    ) -> dict:
        """投递一条协助请求到 pending/；返回完整消息 dict（state="pending"）。

        - topic 为空 / need 非法 → HelpInboxError（不静默落盘）。
        - to_session 为空 = 广播（任何会话可消费）；deadline 为不透明字符串（调用方自证格式）。
        """
        topic = str(topic or "").strip()
        if not topic:
            raise HelpInboxError("topic 必填（拒绝空 topic）")
        need = str(need or "")
        if need not in HELP_NEEDS:
            raise HelpInboxError(f"need 仅允许 {HELP_NEEDS}: {need!r}")
        msg: dict = {
            "id": uuid.uuid4().hex[:12],
            "ts": system_local_now().isoformat(),
            "from_session": str(from_session or "").strip(),
            "to_session": str(to_session or "").strip(),
            "lane_id": str(lane_id or "").strip(),
            "goal_id": str(goal_id or "").strip(),
            "topic": topic,
            "body": str(body or ""),
            "need": need,
            "deadline": str(deadline or "").strip(),
            "state": "pending",
        }
        self._atomic_write_json(self.pending_path(msg["id"]), msg)
        return msg

    def resolve(
        self,
        msg_id: str,
        response: str,
        by_session: str = "",
        decision: str = "resolved",
    ) -> dict:
        """应答: pending/<id> → done/<id>，原字段 + response/by_session/resolved_at。

        - decision 仅允许 {"resolved","declined"}；非法 → HelpInboxError。
        - 消息不在 pending/ 且不在 done/ → HelpInboxNotFoundError。
        - 已在 done/ → 幂等返回既有终态记录（重复应答不覆写历史）。
        - 损坏文件 → HelpInboxCorruptionError（不删原文、不改 state）。
        - 写序: 先落 done/ 再删 pending/（崩溃窗口内两处并存时 done/ 为权威）。
        """
        msg_id = str(msg_id or "").strip()
        if not msg_id:
            raise HelpInboxError("id 必填")
        if decision not in HELP_DECISIONS:
            raise HelpInboxError(f"decision 仅允许 {HELP_DECISIONS}: {decision!r}")

        src = self.pending_path(msg_id)
        if not src.exists():
            done = self.done_path(msg_id)
            if done.exists():
                entry = self._load_message(done)
                if entry is not None:
                    return entry  # 幂等: 已终态，原样返回
                raise HelpInboxCorruptionError(f"done 消息文件损坏: {done}")
            raise HelpInboxNotFoundError(f"协助请求不存在: {msg_id}")

        entry = self._load_message(src)
        if entry is None:
            raise HelpInboxCorruptionError(f"pending 消息文件损坏，拒绝应答: {src}")

        entry["state"] = decision
        entry["response"] = str(response or "")
        entry["by_session"] = str(by_session or "").strip()
        entry["resolved_at"] = system_local_now().isoformat()
        self._atomic_write_json(self.done_path(msg_id), entry)
        try:
            src.unlink()
        except OSError:
            # done/ 已是权威记录; pending 残留只会让该条多显示一次，不丢数据。
            logger.warning("pending 残留删除失败（done 已落盘）: %s", src, exc_info=True)
        return entry

    # ---------------- 读取（零写副作用） ----------------

    def list_pending(
        self,
        need: str | None = None,
        to_session: str | None = None,
    ) -> list[dict]:
        """列未决消息，按 ts 升序（同刻以 id 定序保证确定性）。

        - need 过滤: 精确匹配（None 或空串 = 不过滤）。
        - to_session 过滤: 精确命中或广播消息（to_session 为空）。
        - 损坏文件跳过且计数（见 corrupted_count），不整体失败。
        """
        msgs, _corrupted = self._scan(self._pending_dir)
        if need:
            msgs = [m for m in msgs if str(m.get("need") or "") == need]
        if to_session:
            target = str(to_session)
            msgs = [
                m for m in msgs
                if str(m.get("to_session") or "") in ("", target)
            ]
        msgs.sort(key=lambda m: (str(m.get("ts") or ""), str(m.get("id") or "")))
        return msgs

    def counts(self) -> dict:
        """{"pending": 可解析未决数, "blocking": need==block 且 state==pending 数}."""
        msgs, _corrupted = self._scan(self._pending_dir)
        blocking = sum(
            1
            for m in msgs
            if str(m.get("need") or "") == "block"
            and str(m.get("state") or "pending") == "pending"
        )
        return {"pending": len(msgs), "blocking": blocking}

    def corrupted_count(self) -> int:
        """pending/ 下不可读/不可解析/缺 id 的文件数（健康口径，供上游如实报告）。"""
        _msgs, corrupted = self._scan(self._pending_dir)
        return corrupted

    # ---------------- 内部 ----------------

    @staticmethod
    def _load_message(path: Path) -> dict | None:
        """读取单条消息; 不可读/不可解析/非 dict/缺 id → None（按损坏计）。"""
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(entry, dict) or not entry.get("id"):
            return None
        return entry

    def _scan(self, directory: Path) -> tuple[list[dict], int]:
        """全量扫描一个消息目录: (可解析消息, 损坏计数)。

        目录不存在 → ([], 0)，与 LaneStore.list「账本文件不存在 → 空」同口径；
        *.json.tmp 原子写中间文件不参与扫描。
        """
        if not directory.is_dir():
            return [], 0
        msgs: list[dict] = []
        corrupted = 0
        for path in sorted(directory.glob("*.json")):
            if path.name.endswith(".tmp"):
                continue
            entry = self._load_message(path)
            if entry is None:
                corrupted += 1
                continue
            msgs.append(entry)
        return msgs, corrupted

    def _atomic_write_json(self, path: Path, payload: dict) -> None:
        """tmp + os.replace 原子落盘（与 lane.py 的 _atomic_rewrite 同构，单消息粒度）。"""
        tmp = path.with_name(path.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.debug("help_inbox 临时文件清理失败: %s", tmp, exc_info=True)
