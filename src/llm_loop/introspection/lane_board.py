"""Board 只读聚合（DESIGN-20261105 §4.6 / 裁决 §11 Q5）.

三条硬约束:
- **零写副作用**（A6）：本模块只读 lanes.jsonl / lane_events.jsonl / deployments/*.jsonl，
  不创建目录、不 touch 文件、不写审计。
- **部署条带必须给出**（裁决 Q5）：`deployed_sha` / `main_head` / `in_sync` 是 Board 最该给的比特。
- **degraded 如实**：读不到的数据源进 `degraded[]`，不伪造空值（与 coordination_status 同口径）。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from llm_loop.introspection.lane import TERMINAL_STATUSES, LaneStore
from llm_loop.timekeeping import system_local_now

# service_control 的强契约（runtime/service_control.py）: git_head 必须是
# `re.fullmatch(r"[0-9a-f]{40}")`。Board 只能接受同形状的完整 SHA——短 sha
# 或任意长度十六进制都不是"服务实际记录的 identity"（R4 P2-b）。
_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _sha40(value: Any) -> str:
    """把「40 位十六进制字符串」规范成小写 SHA；其余一律返回空串 = 无值。

    ``True`` / ``123`` / 列表经 ``str()`` 会变成 ``"True"`` / ``"123"``，那是伪造
    版本段（P1）。大小写是同一 identity 的写法差异，归一成小写后比较（R4 P2-b）；
    长度不足 40 或含非十六进制字符则不是 service_control 会写下的值 → unknown。
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text.lower() if _SHA40_RE.match(text) else ""


def _probe_git(workspace_root: str, *args: str) -> tuple[str, str]:
    """只读 git 探针：返回 (输出, 错误)。错误非空 = 不可核验，调用方必须显式 unknown。"""
    if not workspace_root:
        return "", "no_workspace_root"
    try:
        proc = subprocess.run(
            ["git", "-C", workspace_root, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", type(exc).__name__
    if proc.returncode != 0:
        first = (proc.stderr.strip().splitlines() or ["git_failed"])[0]
        return "", first[:80]
    return proc.stdout.strip(), ""


def _probe_versions(workspace_root: str, main_head: str, degraded: list[str]) -> dict[str, Any]:
    """版本条带：checkout HEAD / 可验证 origin/main 各自独立。

    BUG-16: worktree HEAD 绝不冒充 main——detached checkout（例如已合并 PR 的
    head）与 origin/main 可能相差数十个提交，混用会制造假 in_sync=mismatch。
    """
    head, head_err = _probe_git(workspace_root, "rev-parse", "HEAD")
    ref_worktree, _ = _probe_git(workspace_root, "rev-parse", "--abbrev-ref", "HEAD")
    if head_err or not head:
        head = ""
        degraded.append("worktree_head_unknown")
    detached = bool(head) and (not ref_worktree or ref_worktree == "HEAD")

    behind: int | None = None
    if head:
        if main_head:
            # 显式基准：behind 必须相对所报 main，否则两个字段说的不是同一个 ref
            # （P2-2）。本地解析不到该提交就 None，绝不退回 HEAD..origin/main 混算。
            resolved, _ = _probe_git(
                workspace_root, "rev-parse", "--verify", f"{main_head}^{{commit}}"
            )
            base_ref = main_head if resolved else ""
        else:
            base_ref = "origin/main"
        if base_ref:
            raw, err = _probe_git(workspace_root, "rev-list", "--count", f"HEAD..{base_ref}")
            if not err and raw.isdigit():
                behind = int(raw)

    if main_head:
        verified, source, ref = main_head, "explicit", ""
    else:
        verified, err = _probe_git(workspace_root, "rev-parse", "--verify", "origin/main")
        if err or not verified:
            verified, source, ref = "", "unknown", ""
            degraded.append("origin_main_unavailable")
            degraded.append("main_head_unknown")
        else:
            # origin/main 只是本地 remote-tracking ref：没联网就是没核验远端，
            # 不能把它说成"远端已验证"（P2）。新鲜度必须显式 unknown。
            source, ref = "local_tracking", "origin/main"
    return {
        "worktree": {
            "head": head,
            "ref": "" if detached else ref_worktree,
            "detached": detached,
            "behind_main": behind,
        },
        "main": {
            "head": verified,
            "source": source,
            "ref": ref,
            "remote_verified": False,
            "freshness": "unknown",
        },
    }


def _read_desired_deployment(data_root: Path) -> tuple[dict, str]:
    """读 service_control 的 desired deployment（generation / git_head）。

    这是「应该跑哪个 sha」的操作员意图，与 restart-receipt 的「实际在跑」分开；
    两者都不由 Board 推导——缺失即 unknown，不拿 live 或 checkout 顶替。
    """
    path = data_root / "runtime" / "managed_service_deployment.json"
    if not path.is_file():
        return {}, "desired_deployment_missing"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    # UnicodeDecodeError 是 ValueError 子类，既不是 OSError 也不是 JSONDecodeError：
    # 半个 UTF-8 字符必须降级成 unknown，不能炸穿 build_board / 路由（P1）。
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"desired_deployment_unreadable:{type(exc).__name__}"
    if not isinstance(doc, dict) or not _sha40(doc.get("git_head")):
        return {}, "desired_deployment_invalid"
    return doc, ""


def _desired_strip(doc: dict) -> dict[str, Any]:
    generation = doc.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool):
        generation = None
    # 防御第二道：即便调用方传进来未经校验的 doc，也只输出 40 位小写 SHA；
    # 短 sha / 大小写混杂在这里统一收敛，比较口径与 service_control 契约一致。
    sha = _sha40(doc.get("git_head"))
    return {
        "generation": generation,
        "sha": sha,
        "deployment_id": str(doc.get("deployment_id") or ""),
        "source": "managed_service_deployment" if sha else "unknown",
    }


# 同版本两行的"有意义 payload"：这些字段描述 lane 事实本身，任一不同都说明
# 账本被两条不同写入分叉（典型：同一 lane 被两个 owner_session 各写一行）。
# 时间戳/活动时间是易变簿记，不参与比较；完全相同的重复 append 视为幂等重放。
_TIE_MEANINGFUL_FIELDS = (
    "goal_id",
    "branch",
    "worktree",
    "status",
    "base_main_sha",
    "head_sha",
    "verify_ref",
    "paths",
    "contract_changes",
    "lane_role",
    "priority",
    "owner_session_id",
)


def _payload_fingerprint(row: dict) -> str:
    return json.dumps(
        {field: row.get(field) for field in _TIE_MEANINGFUL_FIELDS},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _lane_versions(
    rows: list[dict], *, include_terminal: bool, degraded: list[str]
) -> tuple[list[dict], dict]:
    """按 lane_id 最高 version 取终态（BUG-14a）；冲突/坏版本 fail-closed.

    账本是 append-only：同一 lane 的历史行会同时存在。按文件顺序取首行会把已
    closed lane 的早期 active 行当成在途（ghost lane）。version 单调，故「最高
    version」是确定性终态；同版本且有意义 payload 不同才是真冲突（双写/分叉）
    → 该 lane 不给结论并降级；完全相同的重复行按幂等重放兼容。
    version 必须是 >=1 的 int：bool 是 int 子类、0/负数不可能是合法版本号（P2-2）。
    低版本的历史分叉若已被更高版本决出终态，只留证据、不排除终态（P2-1）。
    """
    latest: dict[str, dict] = {}
    totals: dict[str, int] = {}
    seen_fingerprints: dict[str, dict[int, str]] = {}
    conflicted: dict[str, set[int]] = {}
    invalid: set[str] = set()
    for row in rows:
        lane_id = str(row.get("lane_id") or "").strip()
        if not lane_id:
            degraded.append("lane_row_without_id")
            continue
        version = row.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            degraded.append(f"lane_version_invalid:{lane_id}")
            invalid.add(lane_id)
            continue
        totals[lane_id] = totals.get(lane_id, 0) + 1
        fingerprint = _payload_fingerprint(row)
        per_version = seen_fingerprints.setdefault(lane_id, {})
        if version in per_version:
            # P1-B：同版本不等于同事实。只比 status 会让"同一 lane 被两个
            # owner_session 各写一行"静默取首行；任何有意义字段不同都标记分叉。
            if per_version[version] != fingerprint:
                conflicted.setdefault(lane_id, set()).add(version)
        else:
            per_version[version] = fingerprint
        prev = latest.get(lane_id)
        if prev is None or version > int(prev["version"]):
            latest[lane_id] = {"version": version, "row": row}

    unresolved = set(invalid)
    for lane_id, versions in conflicted.items():
        if int(latest[lane_id]["version"]) in versions:
            # 最高版本自己分叉：终态不确定，该 lane 不给结论。
            degraded.append(f"lane_version_conflict:{lane_id}")
            unresolved.add(lane_id)
        else:
            # P2-1：低版本的历史分叉已被更高版本决出终态，保留证据但不排除终态。
            degraded.append(f"lane_version_conflict_history:{lane_id}:v{max(versions)}")

    selected: list[dict] = []
    for lane_id, entry in latest.items():
        row = entry["row"]
        if lane_id in unresolved:
            continue
        if not include_terminal and str(row.get("status") or "") in TERMINAL_STATUSES:
            continue
        selected.append(row)
    selected.sort(key=lambda e: str(e.get("last_activity") or ""), reverse=True)
    return selected, {
        "lane_rows_total": len(rows),
        "duplicate_lane_ids": sorted(k for k, v in totals.items() if v > 1),
        "lane_conflicts": sorted(unresolved),
    }


def _read_latest_deployment(dep_dir: Path) -> tuple[dict, str]:
    """返回（最新部署行, degraded 原因）。无 target_sha 的行不算部署事实。"""
    if not dep_dir.is_dir():
        return {}, "deployments_missing"
    best: dict = {}
    best_ts = ""
    for path in sorted(dep_dir.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict) or not row.get("target_sha"):
                        continue
                    ts = str(row.get("ts") or "")
                    if ts >= best_ts:
                        best, best_ts = row, ts
        except (OSError, UnicodeDecodeError):
            # 非 UTF-8 字节在迭代中被触发时是 UnicodeDecodeError（ValueError 子类）：
            # 一个坏历史文件不能拖垮整个部署段（与 desired/receipt 同口径）。
            continue
    if not best:
        return {}, "deployments_empty"
    return best, ""


def _read_authoritative_receipt(data_root: Path) -> tuple[dict, str]:
    """读 service_control 的 restart-receipt.json —— 当前实际在跑的 sha 的权威事实。

    历史 ``deployments/*.jsonl`` 是人工部署记录，可能长期停在旧 sha；Board 只读它
    会让 ``in_sync`` 变成永久假 mismatch（部署早就切了，条带还指两年前的 commit）。
    restart-receipt 由 service_control 在重启成功后写入，带
    ``authoritative=true`` 与完整 ``git_head_full``，才是"现在跑的是哪个 sha"。
    """
    path = data_root / "restart-receipt.json"
    if not path.is_file():
        return {}, "restart_receipt_missing"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"restart_receipt_unreadable:{type(exc).__name__}"
    if not isinstance(raw, dict):
        return {}, "restart_receipt_bad_shape"
    # 非 authoritative 的回执（例如子代理手工跑脚本留下）不能冒充部署事实。
    if raw.get("authoritative") is not True:
        return {}, "restart_receipt_not_authoritative"
    sha = _sha40(raw.get("git_head_full"))
    if not sha:
        # 区分"没给"与"给了但不是 40 位十六进制"：两种都不得进 live 段。
        if not str(raw.get("git_head_full") or "").strip():
            return {}, "restart_receipt_no_sha"
        # P2-3：权威回执必须给全 40 位 sha。短/残缺 sha 一旦进 live 段，
        # prefix 比较就能把 exact 判出来（假绿）；来源本身已声明 authoritative，
        # 形状不符只能是坏回执 → 退成 unknown，绝不降格接受。
        return {}, "restart_receipt_bad_sha"
    return {
        "target_sha": sha,
        "ts": str(raw.get("ts") or ""),
        "phase": f"service_control:{raw.get('action') or 'restart'}",
        "source": "restart-receipt",
    }, ""


def _path_overlaps(lanes: list[dict]) -> list[dict]:
    """两两路径交叉检测（U5 防重复开发）：同路径或一方是另一方的前缀即视为重叠。"""
    out: list[dict] = []
    for i in range(len(lanes)):
        for j in range(i + 1, len(lanes)):
            a, b = lanes[i], lanes[j]
            b_paths = list(b.get("paths") or [])
            shared: list[str] = []
            for p in a.get("paths") or []:
                pa = str(p).rstrip("/")
                for q in b_paths:
                    qb = str(q).rstrip("/")
                    if pa == qb or pa.startswith(qb + "/") or qb.startswith(pa + "/"):
                        # 两条声明都记下：重叠语义可能由父路径或子路径任一方表达
                        shared.extend([pa, qb])
                        break
            if shared:
                out.append(
                    {
                        "a": a.get("lane_id"),
                        "b": b.get("lane_id"),
                        "branches": [a.get("branch"), b.get("branch")],
                        "shared_paths": sorted(set(shared)),
                    }
                )
    return out


def _read_help_pending(help_dir: Path) -> tuple[dict[str, int], list[dict], str]:
    """读协助收件箱 pending 统计。返回 (counts, degraded_reason).

    刻意不 import introspection.help_inbox：Board 是纯只读投影，直接读目录即可，
    既不与写入侧耦合，也不会因写入侧未就绪而拖垮 Board。单条损坏跳过，不拖垮统计。
    """
    if not help_dir.is_dir():
        return {}, [], "help_inbox_missing"
    pending = 0
    blocking = 0
    items: list[dict] = []
    try:
        for path in help_dir.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            # UnicodeDecodeError 是 ValueError 子类，既不是 OSError 也不是
            # JSONDecodeError：跨会话写入方留下半个 UTF-8 字符时必须跳过，
            # 否则一条坏文件会拖垮整个 board（与 help_inbox._load_message 同口径）。
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("state") or "pending") != "pending":
                continue
            pending += 1
            need = str(row.get("need") or "")
            if need == "block":
                blocking += 1
            # 保留条目供前端在展开态标注「哪条会话在等什么」，只给总数会有数无门。
            items.append(
                {
                    "id": str(row.get("id") or ""),
                    "need": need,
                    "topic": str(row.get("topic") or ""),
                    "from_session": str(row.get("from_session") or ""),
                    "to_session": str(row.get("to_session") or ""),
                    "lane_id": str(row.get("lane_id") or ""),
                    "since": str(row.get("ts") or ""),
                }
            )
    except OSError:
        return {}, [], "help_inbox_unreadable"
    return {"pending_help": pending, "blocking_help": blocking}, items, ""


def _build_channel(
    lanes: list[dict],
    by_status: dict[str, int],
    head: str,
    audit: Path,
    help_session_dir: str | Path | None,
    degraded: list[str],
) -> dict[str, Any]:
    """总协调通道（§4.5 L3）：多少会话在跑 / 多少待协助 / 多少需决策.

    独立成函数而非内联：build_board 已接近函数行数棘轮上限（120），
    新增聚合不应靠放宽基线通过。
    """
    # ---- 总协调通道（§4.5 L3）：一眼看到「多少会话在跑 / 多少待协助 / 多少需决策」。
    # 默认目录 = <data_dir>/interop/session/pending；audit == <data_dir>/audit。
    help_dir = (
        Path(help_session_dir)
        if help_session_dir
        else audit.parent / "interop" / "session" / "pending"
    )
    help_counts, help_items, help_reason = _read_help_pending(help_dir)
    if help_reason:
        degraded.append(help_reason)

    sessions: list[dict] = [
        {
            "session_id": str(row.get("owner_session_id") or ""),
            "lane_id": str(row.get("lane_id") or ""),
            "goal_id": str(row.get("goal_id") or ""),
            "branch": str(row.get("branch") or ""),
            "role": str(row.get("lane_role") or ""),
            "status": str(row.get("status") or ""),
            "last_activity": str(row.get("last_activity") or ""),
        }
        for row in lanes
    ]
    # 需决策 = 正在合并（卡住要人盯）+ 基线已落后的在途 lane（合并前必须重验）
    #        + need=block 的未决协助请求（有人在等答复）。
    stale_count = sum(
        1
        for row in lanes
        if head
        and str(row.get("base_main_sha") or "")
        and str(row.get("base_main_sha") or "") != head
    )

    merging_pending = by_status.get("merging", 0)
    blocking_help = help_counts.get("blocking_help", 0)

    return {
        "active_lanes": len(lanes),
        "pending_help": help_counts.get("pending_help", 0),
        "blocking_help": blocking_help,
        # 三类性质不同，必须分开给：合并中＝卡在队列等 slot（该看队列），
        # 基线落后＝自己该 rebase（该自己动），等答复＝别人被挡（该回复）。
        # 只给一个合计会让人误判"先处理哪个"。needs_decision 保留为三者之和。
        "merging_pending": merging_pending,
        "baseline_stale": stale_count,
        "needs_decision": merging_pending + stale_count + blocking_help,
        # 数据源可用性：缺失时上游必须显示「不可用」，不得把 0 当真实计数。
        "help_available": bool(help_counts),
        "lanes_available": not any(
            d.startswith("audit_missing") or d.startswith("lanes_unreadable")
            for d in degraded
        ),
        "sessions": sessions,
        # 展开态需要知道「哪条会话在等什么」：只给计数等于有数无门。
        "help_items": help_items,
        "generated_at": system_local_now().isoformat(),
    }


def build_board(
    audit_dir: str | Path,
    *,
    main_head: str = "",
    workspace_root: str = "",
    include_terminal: bool = False,
    help_session_dir: str | Path | None = None,
) -> dict[str, Any]:
    """聚合在途 lane + 部署条带。纯只读；任何数据源缺失都进 degraded。"""
    audit = Path(audit_dir)
    degraded: list[str] = []

    raw_lanes: list[dict] = []
    if not audit.is_dir():
        # A6: 目录不存在时绝不 mkdir（LaneStore.__init__ 会建目录），直接降级。
        degraded.append("audit_missing")
    else:
        try:
            store = LaneStore(audit)
            # 取全量再由本层按版本收敛：store.list() 只按文件顺序返回，不解释 version。
            raw_lanes = store.list(include_terminal=True)
        except Exception as exc:  # noqa: BLE001 — 读不到要如实降级，不能让 Board 整体 500
            degraded.append(f"lanes_unreadable:{type(exc).__name__}")
    lanes, lane_meta = _lane_versions(
        raw_lanes, include_terminal=include_terminal, degraded=degraded
    )

    versions = _probe_versions(workspace_root, str(main_head or "").strip(), degraded)
    head = str(versions["main"]["head"])

    # 权威源优先：restart-receipt 记录"当前实际在跑的 sha"；deployments/*.jsonl
    # 是人工历史记录，可能长期停在旧 sha。权威源缺失才回退，且回退原因如实进 degraded。
    dep_row, dep_reason = _read_authoritative_receipt(audit.parent)
    live_authoritative = not dep_reason
    if dep_reason:
        degraded.append(dep_reason)
        dep_row, hist_reason = _read_latest_deployment(audit / "deployments")
        if hist_reason:
            degraded.append(hist_reason)
    # legacy 兼容：deployed_sha 仍可来自历史行（字段不删），但"实际在跑"只有
    # 权威回执能证明（P1-A）。历史行与 desired 恰好同 sha 也不构成 in_sync 证据。
    deployed_sha = str(dep_row.get("target_sha") or "")
    live_sha = deployed_sha if live_authoritative else ""

    desired_row, desired_reason = _read_desired_deployment(audit.parent)
    if desired_reason:
        degraded.append(desired_reason)
    desired = _desired_strip(desired_row)
    versions["desired"] = desired
    versions["live"] = {
        "sha": live_sha,
        # P2-1：时间戳同样只能由权威回执证明。历史行的 ts 属于 deployed 历史，
        # 挂在 live 段会让人把它读成"最近一次实际在跑的记录"。
        "recorded_at": str(dep_row.get("ts") or "") if live_authoritative else "",
        "source": "restart-receipt" if live_authoritative else "unknown",
        "authoritative": live_authoritative,
    }
    desired_matches_live: bool | None = (
        desired["sha"] == live_sha if desired["sha"] and live_sha else None
    )

    by_status: dict[str, int] = {}
    for row in lanes:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    channel = _build_channel(lanes, by_status, head, audit, help_session_dir, degraded)

    # in_sync 必须精确：部署记录可能是短 sha 或残缺 sha，startswith 会把
    # "head 只是以它开头"误判成"已部署的就是当前 head"（假绿）。三态显式化，
    # 只有 exact 才算同步，prefix_only 单独暴露给 Board 显示。
    if head and live_sha:
        if head == live_sha:
            sync_state = "exact"
        elif len(live_sha) >= 12 and head.startswith(live_sha):
            sync_state = "prefix_only"
        else:
            sync_state = "mismatch"
    elif head and deployed_sha:
        # 只有历史 deployments 行：可展示但不可信（P1-A）——明确 unverified，
        # 绝不因为恰好同 sha 就显示 verified exact。
        sync_state = "unverified"
    else:
        sync_state = "unknown"

    return {
        "generated_at": system_local_now().isoformat(),
        "main_head": head,
        "versions": versions,
        "deployment": {
            "deployed_sha": deployed_sha,
            "deployed_authoritative": live_authoritative,
            "deployed_at": str(dep_row.get("ts") or ""),
            "deployed_phase": str(dep_row.get("phase") or ""),
            "desired_sha": desired["sha"],
            "desired_generation": desired["generation"],
            "desired_matches_live": desired_matches_live,
            "in_sync": sync_state == "exact",
            "sync_state": sync_state,
            "source": str(dep_row.get("source") or "audit/deployments"),
        },
        "channel": channel,
        "lanes": lanes,
        "summary": {
            "inflight": len(lanes),
            "by_status": by_status,
            "overlaps": _path_overlaps(lanes),
            **lane_meta,
        },
        "degraded": degraded,
    }
