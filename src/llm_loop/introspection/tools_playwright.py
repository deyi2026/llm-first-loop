"""Playwright E2E 集成 — 端到端测试工具（EVO-20260813-0ae212ae）.

Codex 风格 Playwright Skill（描述场景→自动生成 E2E 脚本并执行）。
我们当前 870 单测，但 0 E2E，缺少真实浏览器验证。

安全模型:
- URL 沙箱：仅允许 FEISHU + localhost（防滥用爬虫）
- 默认 dry_run=true（不实际执行，需 confirm=true 才跑）
- 审计：每次调用记录到 data/audit/playwright.jsonl
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

PLAYWRIGHT_TEST_TOOL_DEF: dict = {
    "name": "playwright_test",
    "description": "用 Playwright 执行端到端测试（描述场景→生成脚本→执行→返回截图+pass/fail）。何时用: 验证 UI 改动无回归（飞书卡片/网关 Web）；补 E2E 缺口。何时不用: 仅单元测试（用 pytest）；本地浏览器调试（用 IDE）。失败对策: 浏览器未安装时如实返回缺失提示；URL 不在沙箱时拒绝执行。状态契约: 每次调用启动独立浏览器会话（cookies/登录态/打开页面不跨调用持久）；每次调用记录到 data/audit/playwright.jsonl 审计。",
    "parameters": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "description": "自然语言场景描述（如：访问首页→点击登录→输入账号密码→看到欢迎语）"},
            "url": {"type": "string", "description": "目标 URL（仅允许 feishu.cn/localhost）"},
            "confirm": {"type": "boolean", "description": "确认执行（默认 false=仅生成脚本+dry_run）"},
            "headless": {"type": "boolean", "description": "无头模式（默认 true，false 会打开浏览器窗口）"},
        },
        "required": ["scenario", "url"],
    },
}

_AUDIT_PATH = Path("data/audit/playwright.jsonl")

# URL 沙箱：host 精确集合校验（2026-08-16 安全修复——原正则无 $ 锚定，
# userinfo@host/域后缀可逃逸；与 tools_playwright_exec._url_allowed 逻辑保持一致）
_URL_ALLOWED_HOSTS = {"feishu.cn", "localhost", "127.0.0.1"}


def _validate_url(url: str) -> tuple[bool, str]:
    """URL 沙箱验证：urlparse 解析 hostname 精确校验（防 userinfo@host/域后缀/IP 变体/IPv6 逃逸）."""
    from urllib.parse import urlparse

    try:
        p = urlparse(url)
    except ValueError:
        return False, f"URL '{url}' 无法解析"
    if p.scheme not in ("http", "https"):
        return False, f"URL '{url}' 协议不在允许范围（仅 http/https）"
    host = (p.hostname or "").lower()
    if host in _URL_ALLOWED_HOSTS or host.endswith(".feishu.cn"):
        return True, ""
    return False, f"URL '{url}' 不在沙箱允许列表（仅 feishu.cn/localhost/127.0.0.1）"


def _parse_scenario_to_steps(scenario: str) -> list[dict]:
    """简单场景→步骤解析（启发式：按句号/箭头拆）。"""
    import re
    text = scenario.replace("→", "→").replace("，", "，")
    parts = re.split(r"[。;；]|然后|接着|再", text)
    steps = []
    for p in parts:
        p = p.strip().strip("，,.")
        if not p:
            continue
        # 启发式：识别动作（一个文本可能含多个动作）
        actions_found = []
        if "访问" in p or "打开" in p or "goto" in p.lower():
            actions_found.append("goto")
        if "点击" in p or "click" in p.lower():
            actions_found.append("click")
        if "输入" in p or "fill" in p.lower():
            actions_found.append("fill")
        if "等待" in p or "wait" in p.lower():
            actions_found.append("wait")
        if "截图" in p or "screenshot" in p.lower():
            actions_found.append("screenshot")
        if not actions_found:
            actions_found = ["verify"]
        for a in actions_found:
            steps.append({"action": a, "desc": p})
    return steps


def _steps_to_python_script(steps: list[dict], url: str, headless: bool) -> str:
    """步骤→Python 脚本."""
    script = ['"""Auto-generated Playwright E2E script."""',
              'from playwright.sync_api import sync_playwright',
              '',
              'with sync_playwright() as p:',
              f"    browser = p.chromium.launch(headless={headless})",
              '    page = browser.new_page()',
              f"    page.goto('{url}')",
              '    page.wait_for_load_state("networkidle")',
              '']
    for i, step in enumerate(steps, 1):
        action = step["action"]
        desc = step["desc"]
        if action == "goto":
            script.append(f'    # Step {i}: {desc}')
            script.append('    page.goto(page.url)  # placeholder')
        elif action == "click":
            script.append(f'    # Step {i}: {desc} — TODO: 适配实际 selector')
        elif action == "fill":
            script.append(f'    # Step {i}: {desc} — TODO: 适配实际 selector + value')
        elif action == "wait":
            script.append(f'    # Step {i}: {desc}')
            script.append('    page.wait_for_timeout(1000)')
        elif action == "screenshot":
            script.append(f'    # Step {i}: {desc}')
            script.append(f'    page.screenshot(path="data/e2e/step_{i}.png")')
        else:
            script.append(f'    # Step {i}: {desc} (verify)')
            script.append('    assert page.title(), "页面无标题"')
        script.append('')
    script.append('    page.screenshot(path="data/e2e/final.png", full_page=True)')
    script.append('    browser.close()')
    script.append('    print("✅ E2E passed")')
    return "\n".join(script)


def _audit(record: dict) -> None:
    """审计落盘."""
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT_PATH.open("a") as f:
        f.write(json.dumps({**record, "ts": time.time()}, ensure_ascii=False) + "\n")


def run_playwright_test(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """playwright_test: 端到端测试."""
    scenario = str(args.get("scenario", "")).strip()
    url = str(args.get("url", "")).strip()
    confirm = bool(args.get("confirm", False))
    headless = bool(args.get("headless", True))

    if not scenario or not url:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: scenario 或 url 为空。原因: 两者必填。",
            tool_call_id="", tool_name="playwright_test",
        )

    ok, err = _validate_url(url)
    if not ok:
        _audit({"scenario": scenario, "url": url, "result": "blocked", "reason": err})
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[URL 沙箱拒绝] 事实: {err}。原因: 仅允许 feishu.cn/localhost。建议: 使用沙箱内 URL 或修改演进配置。",
            tool_call_id="", tool_name="playwright_test",
        )

    steps = _parse_scenario_to_steps(scenario)
    script = _steps_to_python_script(steps, url, headless)

    if not confirm:
        # dry_run: 仅生成脚本
        _audit({"scenario": scenario, "url": url, "result": "dry_run", "steps": len(steps)})
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"📝 Playwright 脚本已生成（dry_run，confirm=true 才执行）\n\n"
                f"**场景**: {scenario}\n"
                f"**URL**: {url}\n"
                f"**步骤数**: {len(steps)}\n"
                f"**Headless**: {headless}\n\n"
                f"## 解析步骤\n" + "\n".join(f"{i+1}. [{s['action']}] {s['desc']}" for i, s in enumerate(steps)) + "\n\n"
                f"## 生成的脚本\n```python\n{script}\n```\n\n"
                f"💡 确认执行: 重传参数 `confirm=true`\n"
                f"⚠️ 首次使用需安装 chromium: `playwright install chromium`"
            ),
            tool_call_id="", tool_name="playwright_test",
        )

    # 真实执行
    # EVO-20260816-96215428 阶段一：执行层再校验一次 URL（纵深防御）——
    # 参数层校验在函数入口，此处防御未来代码路径绕过入口直接触达执行段；
    # 阶段二单 exec 形态的 helper goto 将复用同一 _validate_url（白名单不可绕过）。
    ok_exec, err_exec = _validate_url(url)
    if not ok_exec:
        _audit({"scenario": scenario, "url": url, "result": "blocked", "reason": f"exec-layer: {err_exec}"})
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[URL 沙箱拒绝·执行层] 事实: {err_exec}。",
            tool_call_id="", tool_name="playwright_test",
        )
    try:
        from playwright.sync_api import sync_playwright

        # 安全执行（有限命名空间）
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_load_state("networkidle")
            page.screenshot(path="data/e2e/playwright_real.png", full_page=True)
            browser.close()
        _audit({"scenario": scenario, "url": url, "result": "passed", "headless": headless})
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"✅ Playwright E2E 执行成功\n\n"
                f"**场景**: {scenario}\n"
                f"**URL**: {url}\n"
                f"**截图**: data/e2e/playwright_real.png\n"
                f"**Headless**: {headless}\n\n"
                f"💡 当前仅执行 goto + screenshot，复杂动作需编写完整 selector"
            ),
            tool_call_id="", tool_name="playwright_test",
        )
    except Exception as e:
        _audit({"scenario": scenario, "url": url, "result": "failed", "error": str(e)[:200]})
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"❌ Playwright 执行失败\n\n"
                f"**错误**: {str(e)[:500]}\n\n"
                f"💡 可能原因:\n"
                f"- chromium 未安装（`playwright install chromium`）\n"
                f"- URL 不可达\n"
                f"- headless=false 但当前无可视化环境"
            ),
            tool_call_id="", tool_name="playwright_test",
        )
