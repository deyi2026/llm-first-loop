#!/usr/bin/env python3
"""M4 desktop_operate live smoke（R3 交付：父会话实测探针的固化版；R6/P2-3 加固）。

⚠️ 本脚本会在用户桌面开/关**临时窗口**（Preview 打开本脚本自建的
    临时 PNG 再关闭），需用户在场且知情后才可运行。
    绝不触碰用户其它窗口：目标窗口按 bundle_id + title 精确定位，且
    title 是本脚本生成的唯一临时文件名。

流程（真实工具链路，进程内 ctypes，无 pyobjc）：
  0. 环境自检（锁屏/无 GUI → 退出码 3，不开窗；R5）；
  1. 在**不可预测的临时目录**（tempfile.mkdtemp，mktemp -d 同义）生成最小
     PNG（文件名固定 lfl-m4-live.png——窗口 title 绑定依赖它）；
  2. `open -a Preview` 打开它（CalledProcessError/TimeoutExpired 映射到
     退出码 3=环境不可用，不以 traceback 逃逸——R6/P2-3），按
     bundle_id=com.apple.Preview + title 精确
     等到我们的窗口出现；
  3. AX snapshot 找 AXCloseButton 节点（真机编码 role=AXButton +
     subrole=AXCloseButton；只读）；
  4. dry_run click（取 confirm_token）→ 打印回执关键字段；
  5. （--dry-run-only 则到此为止）apply click（AXCloseButton）→ 打印回执
     关键字段（ok/error_code/applied/verified/pre_sha256/post_sha256）；
  6. 校验窗口已消失；
  7. 清理：若窗口仍在（含 --dry-run-only / apply 被门控拒绝），对本脚本
     **自建窗口**的关闭钮做一次直接 AXPress（不走工具门控，仅限清理自己的
     临时窗口）；临时目录整体删除（--keep-artifacts 时保留）。

--dry-run-only：只做只读探测（dry_run 回执 + 令牌签发），不投递任何事件；
该模式工具实例 writes_enabled=False（纵深防御：即使误调 apply 也是
writes_disabled 拒绝）。注意 D7 门：apply 需要 HID idle ≥ 60s（用户停止
键鼠 1 分钟），否则按 user_present 拒绝——这是设计内行为，非缺陷。

用法：
  PYTHONPATH=src python scripts/desktop_operate_live_smoke.py            # 全流程
  PYTHONPATH=src python scripts/desktop_operate_live_smoke.py --dry-run-only

退出码（R5 起区分「门控拒绝」与「环境不可用」）：0=全流程通过且窗口确认消失；
2=确定性门控拒绝（预期行为，看指引；如 foreground_changed/user_present）；
3=环境不可用（屏幕锁定、无 GUI 会话、AX 不可读、前台 app 探测不可用、
   open 启动 Preview 失败/超时（R6/P2-3 起含此类）——先 desktop_perceive(status)
   自检）；1=其它链路失败（窗口未找到、投递失败等）。
   注：锁屏下 AX 读取与投递均被拒（ax_window_unbound/ax_unavailable 的真实
   归因常是锁屏而非辅助功能授权——R5 修正：不再只提示授权）。

前置：macOS + 辅助功能授权（AX）+ 屏幕录制授权（CG 窗口标题）+ 未锁屏。
live 正向投递证据以父会话在真机复跑为准（本脚本只是可复用探针）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_REPO_SRC) not in sys.path and not any(str(p).endswith("/src") for p in sys.path):
    sys.path.insert(0, str(_REPO_SRC))

from llm_loop.core.message import ToolCall  # noqa: E402
from llm_loop.desktop import macos_actuate  # noqa: E402
from llm_loop.desktop.backend_macos import backend_for_platform  # noqa: E402
from llm_loop.tools.builtin.desktop_operate import DesktopOperateTool  # noqa: E402
from llm_loop.tools.registry import ToolRegistry  # noqa: E402

# R6/P2-3：不再使用可预测的 /tmp 固定路径（共享主机上存在预置符号链接被
# 覆盖的风险）——临时目录由 tempfile.mkdtemp 生成（不可预测路径 + 独占
# 创建），结束时整体清理；PNG 文件名固定（窗口 title 绑定依赖它），但
# 所在目录每次运行都不同。
PNG_NAME = "lfl-m4-live.png"
AUDIT_NAME = "audit.jsonl"
BUNDLE = "com.apple.Preview"
WINDOW_TITLE = PNG_NAME
OPEN_WAIT_S = 15.0
GONE_WAIT_S = 5.0
SESSION_ID = "lfl-m4-live-smoke"
TMP_PREFIX = "lfl-m4-live-"


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_tiny_png(path: Path) -> None:
    """8x8 纯红 PNG（纯 stdlib：IHDR/IDAT/IEND，无第三方依赖）。"""
    w = h = 8
    raw = b"".join(b"\x00" + b"\xE0\x20\x30" * w for _ in range(h))
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw, 9))
    png += _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def _receipt_key_fields(receipt: dict) -> dict:
    """只挑回执的关键字段打印（不整窗元数据倾倒，隐私面最小）。"""
    keys = (
        "ok", "error_code", "applied", "verified", "dry_run",
        "risk_class", "needs_confirmation", "confirm_token",
        "pre_sha256", "post_sha256", "hid_idle_ms", "guidance",
        "target_identity", "world_version",
    )
    return {k: receipt.get(k) for k in keys if k in receipt}


def _print_receipt(step: str, receipt: dict) -> None:
    print(f"[{step}] {_receipt_key_fields(receipt)}", flush=True)


def _find_own_window(backend, timeout_s: float):
    """按 bundle_id+title 精确定位本脚本自建窗口（唯一命中才继续）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        windows = [w for w in backend.list_windows() if w.on_screen]
        hits = [w for w in windows if w.bundle_id == BUNDLE and w.title == WINDOW_TITLE]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:  # 同名多窗（理论不可能：文件名唯一）——拒绝，不猜
            print(f"[abort] 同名窗口 {len(hits)} 个，拒绝操作", flush=True)
            return None
        time.sleep(0.5)
    return None


def _window_gone(backend, window_id: int) -> bool:
    deadline = time.monotonic() + GONE_WAIT_S
    while time.monotonic() < deadline:
        if backend.get_window(window_id) is None:
            return True
        time.sleep(0.5)
    return backend.get_window(window_id) is None


def _cleanup_close_own_window(window, close_ax_ref: str) -> bool:
    """最后手段清理：对本脚本自建窗口的关闭钮直接 AXPress（不走工具门控）。

    仅限 bundle_id+title 命中的自建窗口；失败则提示用户手动关闭。
    """
    try:
        el, failure = macos_actuate.resolve_element_by_axref(window, close_ax_ref)
        if el is None:
            print(f"[cleanup] 关闭钮解析失败（{failure}），请手动关闭窗口 {WINDOW_TITLE}", flush=True)
            return False
        try:
            err = macos_actuate.ax_press(el)
        finally:
            el.release()
        if err != 0:
            print(f"[cleanup] AXPress err={err}，请手动关闭窗口 {WINDOW_TITLE}", flush=True)
            return False
        print("[cleanup] 已对本脚本自建窗口投递 AXCloseButton AXPress", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 - 清理失败如实报告，不掩盖
        print(f"[cleanup] 关闭自建窗口异常: {type(exc).__name__}: {exc}", flush=True)
        return False


def _audit_sink(audit_path: Path):
    """审计 sink 工厂（R6/P2-3：审计文件随不可预测临时目录生成）。"""
    def sink(row: dict) -> None:
        line = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(f"[audit] {line}", flush=True)
    return sink


def _env_selfcheck(backend) -> int | None:
    """0. 环境自检（R5：先排除锁屏/无 GUI，再开窗口）。通过返回 None。"""
    session = backend.session_snapshot()
    if session.screen_locked:
        print("[env-unavailable] 屏幕已锁定（screen_locked=true）：锁屏下 AX 读取与"
              "投递均被拒；解锁后重跑（R5 自检，desktop_perceive(status) 同口径）。",
              flush=True)
        return 3
    if not session.gui_available:
        print("[env-unavailable] 无图形控制台会话（gui_available=false）；需在已登录"
              "桌面会话内运行。", flush=True)
        return 3
    return None


def _open_target_window(backend, tmp_png: Path):
    """1. 自建 PNG（不可预测临时目录内）+ open -a Preview + 精确绑定窗口。

    R6/P2-3：open 的 CalledProcessError/TimeoutExpired 映射到退出码 3
    （环境不可用），不再以 traceback 逃逸绕过退出码分类。
    返回 (window | None, exit_code | None)。
    """
    make_tiny_png(tmp_png)
    print(f"[setup] 已生成 {tmp_png}（{tmp_png.stat().st_size}B）", flush=True)
    try:
        subprocess.run(["open", "-a", "Preview", str(tmp_png)], check=True, timeout=10)
    except subprocess.CalledProcessError as exc:
        print(f"[env-unavailable] open 启动 Preview 失败（returncode={exc.returncode}）："
              "无法开自建窗口，按环境不可用处理。", flush=True)
        return None, 3
    except subprocess.TimeoutExpired:
        print("[env-unavailable] open 启动 Preview 超时（10s）：按环境不可用处理。",
              flush=True)
        return None, 3
    print("[setup] open -a Preview 已发出，等待窗口出现…", flush=True)
    window = _find_own_window(backend, OPEN_WAIT_S)
    if window is None:
        print(f"[abort] {OPEN_WAIT_S:.0f}s 内未找到 bundle={BUNDLE} title={WINDOW_TITLE} 的窗口"
              "（需屏幕录制授权以读 CG 标题；Preview 可能未打开）", flush=True)
        return None, 1
    print(f"[setup] 目标窗口 window_id={window.window_id} pid={window.pid} "
          f"title={window.title!r} bounds={window.bounds_pt}", flush=True)
    return window, None


def _find_close_button(backend, window):
    """2. 只读 snapshot：找关闭钮（真机编码 role=AXButton+subrole=AXCloseButton）。"""
    view = backend.ax_snapshot(window, 4, 1500)
    if not view.available:
        # R5 归因修正：ax_window_unbound/ax_unavailable 在真机的常见真实原因是
        # 屏幕自动锁定（锁屏下 AX 读取与投递均被拒），并非只有辅助功能授权。
        print(f"[env-unavailable] AX 快照不可用（{view.failure}；锁屏或 AX 不可读——"
              "先用 desktop_perceive(status) 自检；锁屏下 AX 读取与投递均被拒；"
              "辅助功能授权绑定启动进程，重启宿主后需复核）", flush=True)
        _cleanup_close_own_window(window, "0")  # 尽力关闭（可能同样失败，如实报告）
        return None, 3
    close_nodes = [n for n in view.nodes if (n.subrole or "") == "AXCloseButton"]
    if not close_nodes:
        print("[abort] AX 树中未找到 AXCloseButton（可用节点见下）", flush=True)
        for node in view.nodes[:12]:
            print(f"        {node.ax_ref} role={node.role} subrole={node.subrole}", flush=True)
        return None, 1
    target = close_nodes[0]
    print(f"[snapshot] 节点数={len(view.nodes)} 选中关闭钮 ax_ref={target.ax_ref} "
          f"role={target.role} subrole={target.subrole}", flush=True)
    return target, None


def _frontmost_precheck(backend, window, close_ax_ref: str, dry_run_only: bool) -> int | None:
    """2b. 前台 app 探测（R5 门控判据；lsappinfo 口径）。通过返回 None。"""
    front = backend.frontmost_app_bundle()
    print(f"[setup] 前台 app（lsappinfo 口径，R5 判据）= {front}", flush=True)
    if front is None:
        print("[env-unavailable] 前台 app 探测不可用（lsappinfo front/list 无匹配或"
              "不可执行）——apply 会 fail-closed（foreground_changed）", flush=True)
        if not dry_run_only:
            _cleanup_close_own_window(window, close_ax_ref)
            return 3
        print("[note] --dry-run-only：dry_run 不做前台门控，继续只读探测", flush=True)
    elif front != window.bundle_id:
        print(f"[note] 前台 app（{front}）≠ 目标窗口所属 app（{window.bundle_id}）："
              "apply 将按 foreground_changed 拒绝（用户切走即拒，属设计内门控）",
              flush=True)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 desktop_operate live smoke（自建临时窗口）")
    parser.add_argument("--dry-run-only", action="store_true",
                        help="只做只读探测（dry_run + 令牌签发），不投递；writes_enabled=False 纵深防御")
    parser.add_argument("--keep-artifacts", action="store_true",
                        help="结束时保留临时目录（PNG + 审计 JSONL）；默认整体删除"
                             "（审计行已逐行打印到 stdout，不因清理丢失）")
    args = parser.parse_args()

    print("⚠️  本脚本会在用户桌面开/关临时窗口（Preview + 自建临时 PNG），"
          "需用户在场且知情。绝不触碰用户其它窗口（按 bundle_id+title 精确定位）。",
          flush=True)
    if sys.platform != "darwin":
        print("[abort] 仅支持 macOS", flush=True)
        return 1

    backend = backend_for_platform("darwin")
    if backend is None:
        print("[abort] macOS 后端不可用", flush=True)
        return 1

    # R6/P2-3：不可预测临时目录（mktemp -d 同义；独占创建），结束时整体清理。
    tmp_dir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX))
    tmp_png = tmp_dir / PNG_NAME
    audit_path = tmp_dir / AUDIT_NAME
    print(f"[setup] 临时目录 {tmp_dir}（默认结束时删除；--keep-artifacts 保留）",
          flush=True)
    try:
        return _run_smoke(args, backend, tmp_png, audit_path)
    finally:
        if args.keep_artifacts:
            print(f"[artifacts] --keep-artifacts：保留临时目录 {tmp_dir}", flush=True)
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            print(f"[cleanup] 已删除临时目录 {tmp_dir}", flush=True)


def _run_smoke(args, backend, tmp_png: Path, audit_path: Path) -> int:
    """主流程（main 之外拆出，保证每函数 ≤120 行）：自检→开窗→找钮→工具链路。"""
    code = _env_selfcheck(backend)
    if code is not None:
        return code
    window, code = _open_target_window(backend, tmp_png)
    if window is None:
        return code or 1
    target, code = _find_close_button(backend, window)
    if target is None:
        return code or 1
    code = _frontmost_precheck(backend, window, target.ax_ref, args.dry_run_only)
    if code is not None:
        return code

    # ── 3. 真实工具链路：dry_run → apply ───────────────────────────────
    tool = DesktopOperateTool(
        backend=backend,
        session_id_getter=lambda: SESSION_ID,
        audit_sink=_audit_sink(audit_path),
        # --dry-run-only 纵深防御：writes_enabled=False（dry_run 回执在写开关
        # 检查之前返回，不受影响；误调 apply 也只会 writes_disabled）。
        writes_enabled=not args.dry_run_only,
    )
    registry = ToolRegistry()
    registry.register(tool)

    def _dispatch(**kwargs) -> dict:
        result = registry.execute(
            ToolCall(id=f"smoke-{time.monotonic_ns()}", name="desktop_operate", arguments=kwargs)
        )
        return json.loads(result.content)

    print(f"[audit-file] {audit_path}（随临时目录默认删除，行内容已打印到 stdout）",
          flush=True)
    call = {"do": "click", "window_id": window.window_id, "target": {"ax_ref": target.ax_ref}}
    dry = _dispatch(**call, dry_run=True)
    _print_receipt("dry_run", dry)
    if not dry.get("ok"):
        print("[abort] dry_run 失败（见上）", flush=True)
        _cleanup_close_own_window(window, target.ax_ref)
        return 1
    token = dry.get("confirm_token") or ""
    if not token:
        print("[abort] dry_run 未签发 confirm_token", flush=True)
        _cleanup_close_own_window(window, target.ax_ref)
        return 1

    if args.dry_run_only:
        print("[done] --dry-run-only：未投递任何事件；关闭自建窗口后退出", flush=True)
        ok_gone = _cleanup_close_own_window(window, target.ax_ref) and _window_gone(backend, window.window_id)
        return 0 if ok_gone else 2

    apply_receipt = _dispatch(**call, dry_run=False, confirm_token=token)
    _print_receipt("apply", apply_receipt)
    error_code = apply_receipt.get("error_code")

    if not apply_receipt.get("ok"):
        gate_like = {
            "user_present", "writes_disabled", "exec_mode_blocked", "review_required",
            "confirm_token_invalid", "confirm_token_replayed", "confirm_token_mismatch",
            "confirm_token_expired", "foreground_changed",
        }
        closed = _cleanup_close_own_window(window, target.ax_ref)
        gone = closed and _window_gone(backend, window.window_id)
        if error_code in gate_like:
            note = "（D7 在场门：停止键鼠 ≥60s 后重跑；或宿主配置 force 凭据）" if error_code == "user_present" else ""
            print(f"[gate-refused] apply 被确定性拒绝 error_code={error_code} {note}", flush=True)
            return 2
        print(f"[fail] apply 失败 error_code={error_code}（清理结果: gone={gone}）", flush=True)
        return 1

    # ── 4. 校验窗口已消失 ─────────────────────────────────────────────
    gone = _window_gone(backend, window.window_id)
    print(f"[verify] 窗口 {window.window_id} 已消失: {gone}（post_sha256 见 apply 回执）", flush=True)
    if not gone:
        closed = _cleanup_close_own_window(window, target.ax_ref)
        gone = closed and _window_gone(backend, window.window_id)
        print(f"[verify-2] 兜底清理后再查: {gone}", flush=True)
    return 0 if gone else 1


if __name__ == "__main__":
    sys.exit(main())
