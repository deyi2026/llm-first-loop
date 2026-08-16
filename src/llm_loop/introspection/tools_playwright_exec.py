"""playwright_exec(code) — 单 exec 浏览器工具（EVO-20260816-bfb9f215 阶段二）.

设计来源: docs/local/EVAL-20260816-playwright-single-exec.md + Hermes browser_exec 调研。
形态: 模型写 Python，每次调用在**独立子进程**执行（解释器状态零持久），
预置 helper 七件套（goto/click/fill/wait/js/screenshot/axtree_text）——
砍 cdp 原始调用（我方无此需求）。

安全模型（2026-08-16 DSH 独立审查后补强，审查见 /tmp/dsh_audit_out.txt 存档）:
- URL 沙箱: host 精确集合校验（urlparse 解析 hostname，仅 feishu.cn(含子域)/
  localhost/127.0.0.1；防 userinfo@host、域后缀、IP 变体、IPv6 逃逸）
- 命名空间隔离: 模型代码经 _run_model 在独立命名空间 exec，仅可见 helper 七件套
  + 内置；_page/_browser/_pw/_OUT 内部对象不可见（防裸 API 绕过 URL 白名单）
- AST 静态门控（纵深防御）: 拦截字面 import playwright + 动态导入
  （__import__/import_module）+ 动态执行（exec/eval/compile）+ sys.modules 取模块
- confirm=true 才执行（默认 dry_run 仅回显脚本）
- 子进程隔离 + 超时终止; 审计落盘 data/audit/playwright.jsonl
- 明确开放面（设计未承诺防护）: 模型代码在子进程内可读写工作区文件、发起任意
  网络请求（requests/urllib/socket 未被禁）——等价于完全可信 shell，信任边界
  由产品方显式决策（见 docs/local/EVAL 报告与审计结论）
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.tools_playwright import _AUDIT_PATH

TOOL_NAME = "playwright_exec"

# ── 钉死的 helper 摘要（≤2KB, 写进工具描述; 对齐 AX L1 规范）──
# 依据: Hermes 108 次 A/B 证明钉死摘要 ≡ 动态全文（我方未独立复核 token 数字,
# 验收基准 scripts/bench_playwright_exec.py 事后复核）。
_HELPER_SUMMARY = """预置 helper（脚本内直接调用，无需 import）:
- goto(url): 打开页面（仅 feishu.cn/localhost/127.0.0.1，白名单外报错）并等 networkidle
- click(selector): CSS 选择器点击
- fill(selector, value): 输入框填值
- wait(ms) 或 wait("selector:xxx"): 等毫秒 / 等元素出现
- js(expr): 执行 JS 返回结果（JSON 可序列化）
- axtree_text(): 页面无障碍树转文本（读页面内容首选，比 screenshot 省 token）
- screenshot(name): 截图存 data/e2e/<session>/<name>.png，返回路径
脚本首行写 ≤60 字符注释当步骤标签。聚合/核对用代码做（append 到 JSON 再读回），别在脑里做。"""

PLAYWRIGHT_EXEC_TOOL_DEF: dict = {
    "name": TOOL_NAME,
    "description": (
        "执行你写的 Python 浏览器脚本（单 exec 形态：一次调用打包 navigate+act+extract，"
        "预置 helper 见下）。何时用: 需要交互/登录态/JS 渲染的 E2E 验证。何时不用: "
        "纯 HTTP 可取的公开页面（先用 web_fetch，失败或返回壳页面才升级浏览器）；"
        "单元测试（用 pytest）。失败对策: chromium 缺失/URL 不可达/超时均如实返回错误+指引。"
        "状态契约: 每次调用独立子进程（Python 变量/浏览器会话均不跨调用持久）；"
        "产物落盘 data/e2e/<session>/ 持久；长任务拆多次中型调用防超时丢进度；"
        "审计落盘 data/audit/playwright.jsonl。安全门控: 禁止 import playwright"
        "（必须走 helper）；goto 白名单不可绕过；confirm=true 才真实执行。\n\n"
        + _HELPER_SUMMARY
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python 脚本（使用预置 helper，禁止 import playwright；首行写 ≤60 字符步骤注释）"},
            "session": {"type": "string", "description": "产物目录名（默认 default），用于 data/e2e/<session>/ 归类"},
            "confirm": {"type": "boolean", "description": "确认执行（默认 false=dry_run 仅回显脚本+静态检查）"},
            "timeout_s": {"type": "integer", "description": "子进程超时秒（默认 60，上限 300）"},
        },
        "required": ["code"],
    },
}

# ── 子进程引导脚本（helper 实现; 模型代码经命名空间隔离执行，详见 _run 与文件头安全模型）──
_PREAMBLE = '''
import json, re, sys, time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

_SESSION = __SESSION__
_OUT = Path("data/e2e") / _SESSION
_OUT.mkdir(parents=True, exist_ok=True)

_pw = sync_playwright().start()
_browser = _pw.chromium.launch(headless=True)
_page = _browser.new_page()

# URL 沙箱：host 精确集合校验（防 userinfo@host / 域后缀 / IP 变体 / IPv6 逃逸）
_URL_ALLOWED_HOSTS = {"feishu.cn", "localhost", "127.0.0.1"}

def _url_allowed(url):
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower()
    return host in _URL_ALLOWED_HOSTS or host.endswith(".feishu.cn")

def goto(url):
    if not _url_allowed(url):
        raise PermissionError(f"URL 沙箱拒绝: {url}（仅 feishu.cn/localhost/127.0.0.1）")
    _page.goto(url)
    _page.wait_for_load_state("networkidle")
    return _page.title()

def click(selector):
    _page.click(selector)
    return True

def fill(selector, value):
    _page.fill(selector, value)
    return True

def wait(target):
    if isinstance(target, str) and target.startswith("selector:"):
        _page.wait_for_selector(target[len("selector:"):])
    else:
        _page.wait_for_timeout(int(target))
    return True

def js(expr):
    return _page.evaluate(expr)

def axtree_text():
    # Playwright Python 新版无 page.accessibility 属性——走 CDP（对齐 Hermes 的 Accessibility.getFullAXTree）
    cdp = _page.context.new_cdp_session(_page)
    data = cdp.send("Accessibility.getFullAXTree")
    raw = data.get("nodes", [])
    nodes = {n["nodeId"]: n for n in raw}
    children = {}
    roots = []
    for n in raw:
        pid = n.get("parentId")
        if pid and pid in nodes:
            children.setdefault(pid, []).append(n["nodeId"])
        else:
            roots.append(n["nodeId"])
    lines = []
    def _walk(nid, depth):
        if len(lines) >= 500:  # 行数熔断（防巨型页面 token 爆炸）
            return
        n = nodes.get(nid)
        if not n:
            return
        role = (n.get("role") or {}).get("value", "")
        name = (n.get("name") or {}).get("value", "")
        if name:
            lines.append("  " * depth + f"[{role}] {name}")
        for cid in children.get(nid, []):
            _walk(cid, depth + 1)
    for r in roots:
        _walk(r, 0)
    text = "\\n".join(lines)
    if len(text) > 20000:  # 字符熔断
        text = text[:20000] + "\\n... [截断: axtree 超 20000 字符，用 js() 精确取目标区域]"
    return text

def screenshot(name):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))[:60]
    path = _OUT / f"{safe}.png"
    _page.screenshot(path=str(path), full_page=True)
    return str(path)

def _cleanup():
    try:
        _browser.close()
        _pw.stop()
    except Exception:
        pass  # fail-open: 清理兜底，浏览器/驱动已退出时静默（审计已在主流程落盘）

import atexit
atexit.register(_cleanup)

# ── 命名空间隔离（2026-08-16 安全修复，EVO-20260816-bfb9f215 阶段二补强）──
# 模型代码在独立命名空间执行，仅可见 helper 与内置；_page/_browser/_pw/_OUT
# 等内部对象不可见（防裸 API 绕过白名单）。helper 闭包仍引用自身模块全局，
# 功能不受影响。文件/网络访问仍属设计开放面（见文件头安全模型）。
_HELPERS = {
    "goto": goto, "click": click, "fill": fill, "wait": wait,
    "js": js, "axtree_text": axtree_text, "screenshot": screenshot,
}

def _run_model(code):
    ns = {"__builtins__": __builtins__, "__name__": "__model__"}
    ns.update(_HELPERS)
    exec(compile(code, "<model>", "exec"), ns)

_run_model(__MODEL_CODE__)
'''


def _scan_code(code: str) -> tuple[bool, str]:
    """AST 静态门控（纵深防御；主防线为命名空间隔离 _run_model）.

    拦截（2026-08-16 安全补强，覆盖 DSH 审查 payload 全形态）:
    - 字面 import playwright（原有）
    - 动态导入: __import__(...)/importlib.import_module(...)/import_module(...)
    - 动态执行: exec/eval/compile 字面调用
    - sys.modules[...] 取已加载模块（preamble 已 import playwright.sync_api，
      此路径原可直接取模块）
    注: 即使动态导入成功，模型代码所在命名空间无 _page/_browser/_pw 引用，
    无法触碰受管浏览器实例（命名空间隔离为真正防线，本门控为纵深）。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "playwright":
                    return False, "禁止 import playwright——必须使用预置 helper（goto/click/fill/wait/js/screenshot/axtree_text）"
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "playwright":
            return False, "禁止 from playwright import——必须使用预置 helper"
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name in {"__import__", "import_module"}:
                return False, "禁止动态导入（__import__/import_module）——必须使用预置 helper"
            if name in {"exec", "eval", "compile"}:
                return False, "禁止动态执行（exec/eval/compile）——必须使用预置 helper"
            # getattr 间接引用: getattr(importlib, 'import_module')('playwright')
            if name in {"getattr"} and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str) and node.args[1].value in {"__import__", "import_module", "exec", "eval", "compile"}:
                return False, f"禁止 getattr 间接引用（{node.args[1].value}）——必须使用预置 helper"
        elif isinstance(node, ast.Subscript):
            v = node.value
            if isinstance(v, ast.Attribute) and v.attr == "modules" and isinstance(v.value, ast.Name) and v.value.id == "sys":
                return False, "禁止经 sys.modules 取已加载模块——必须使用预置 helper"
        elif isinstance(node, ast.Attribute) and node.attr == "modules" \
                and isinstance(node.value, ast.Name) and node.value.id == "sys":
            # sys.modules 的任何访问形态（含 .get/.keys 等方法调用）——preamble 已加载
            # playwright.sync_api，直接取模块即可绕过 import 拦截
            return False, "禁止访问 sys.modules——必须使用预置 helper"
    return True, ""


def _audit(record: dict) -> None:
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_PATH.open("a") as f:
        f.write(json.dumps({**record, "tool": TOOL_NAME, "ts": time.time()}, ensure_ascii=False) + "\n")


def run_playwright_exec(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """playwright_exec: 单 exec 浏览器脚本执行."""
    code = str(args.get("code", "")).strip()
    session = str(args.get("session", "default")).strip() or "default"
    confirm = bool(args.get("confirm", False))
    timeout_s = max(5, min(int(args.get("timeout_s", 60) or 60), 300))

    if not code:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: code 为空。原因: 必填。建议: 传入使用预置 helper 的 Python 脚本。",
            tool_call_id="", tool_name=TOOL_NAME,
        )

    ok, err = _scan_code(code)
    if not ok:
        _audit({"session": session, "result": "blocked", "reason": err})
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[静态门控拒绝] 事实: {err}。原因: 防裸 API 绕过 URL 白名单。建议: 改用 helper goto/click/fill。",
            tool_call_id="", tool_name=TOOL_NAME,
        )

    if not confirm:
        _audit({"session": session, "result": "dry_run", "code_chars": len(code)})
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"📝 playwright_exec 静态检查通过（dry_run，confirm=true 才执行）\n\n"
                f"**session**: {session}\n**code**: {len(code)} 字符\n**timeout**: {timeout_s}s\n\n"
                f"💡 确认执行: 重传参数 `confirm=true`"
            ),
            tool_call_id="", tool_name=TOOL_NAME,
        )

    # 真实执行：独立子进程（解释器/浏览器均不跨调用持久）。
    # 模型代码以 __MODEL_CODE__ 注入，由 preamble 的 _run_model 在隔离命名空间执行
    # （2026-08-16 安全修复：不再直接拼接进同一模块作用域）
    script = (
        _PREAMBLE.replace("__SESSION__", repr(session)).replace("__MODEL_CODE__", repr(code))
    )
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
            tf.write(script)
            tmp_path = tf.name
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=timeout_s,
            env={**os.environ},
        )
        out = (proc.stdout or "")[-8000:]
        err_tail = (proc.stderr or "")[-2000:]
        if proc.returncode == 0:
            _audit({"session": session, "result": "passed", "code_chars": len(code)})
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"✅ playwright_exec 执行成功（session={session}）\n\n**stdout**:\n```\n{out or '(空)'}\n```",
                tool_call_id="", tool_name=TOOL_NAME,
            )
        _audit({"session": session, "result": "failed", "rc": proc.returncode, "error": err_tail[:200]})
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"❌ playwright_exec 执行失败（exit={proc.returncode}）\n\n"
                f"**stderr**:\n```\n{err_tail or '(空)'}\n```\n**stdout**:\n```\n{out[-2000:] or '(空)'}\n```\n\n"
                f"💡 常见原因: selector 未命中（先 axtree_text() 看页面结构）/ URL 白名单外 / chromium 未安装"
            ),
            tool_call_id="", tool_name=TOOL_NAME,
        )
    except subprocess.TimeoutExpired:
        _audit({"session": session, "result": "timeout", "timeout_s": timeout_s})
        return ToolResult(
            status=ToolResultStatus.TIMEOUT,
            content=(
                f"⏱️ playwright_exec 超时（{timeout_s}s）——子进程已终止。\n"
                f"💡 建议: 拆多次中型调用（navigate 一次、act+extract 一次）；已完成的截图/产物在 data/e2e/{session}/ 不丢"
            ),
            tool_call_id="", tool_name=TOOL_NAME,
        )
    except Exception as e:
        _audit({"session": session, "result": "error", "error": str(e)[:200]})
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"❌ playwright_exec 执行异常: {str(e)[:500]}\n💡 chromium 未安装时先 `playwright install chromium`",
            tool_call_id="", tool_name=TOOL_NAME,
        )
    finally:
        if tmp_path:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
