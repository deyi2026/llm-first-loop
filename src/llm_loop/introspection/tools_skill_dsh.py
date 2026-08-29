"""DSH Plugin 索引适配器（SDD-20260829 T2-T4，2026-08-29）.

skill_list/skill_load 的 DSH 生态互操作层：awesome-dsh-plugin 人工审核清单只读解析。
红线（SDD §2/§3.3）: 仅 GET 白名单域 raw.githubusercontent.com；不下载不执行任何插件代码；
断网/限额失败如实标注，不影响本地技能段（零回归）。
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

AWESOME_README_URL = (
    "https://raw.githubusercontent.com/awesome-dsh-plugin/awesome-dsh-plugin/HEAD/README.md"
)
ALLOWED_URL_PREFIX = "https://raw.githubusercontent.com/"  # 白名单域（SDD §3.2）
INDEX_TTL_S = 86400  # 24h
FETCH_TIMEOUT_S = 8
README_SNIPPET_CHARS = 2000

_ENTRY_RE = re.compile(
    r"^-\s+\[([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)\]"  # [owner/repo]
    r"\(https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/?\)"  # (github url)
    r"\s+-\s+(.+)$"  # " - " 一行描述（T1 实测分隔符）
)


def _index_path(host: Any) -> Path | None:
    """缓存路径 data/audit/dsh_index.json（audit_dir 未注入返回 None → 免缓存模式）."""
    d = getattr(host, "audit_dir", None)
    return Path(d) / "dsh_index.json" if d else None


def _fetch(url: str) -> str:
    """白名单域受限 GET（非 raw.githubusercontent.com 一律拒绝）."""
    if not url.startswith(ALLOWED_URL_PREFIX):
        raise PermissionError(f"非白名单域请求被拒绝: {url[:60]}")
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as r:
        return r.read().decode("utf-8", "ignore")


def parse_awesome(readme: str) -> list[dict]:
    """解析 awesome 清单: 分类标题（##/###）下的 `- [owner/repo](url) - desc` 条目.

    非插件段（Contents/Contributing/Disclaimer 等）因不含条目模式自然跳过。
    """
    plugins: list[dict] = []
    category = ""
    for line in readme.splitlines():
        h = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if h:
            title = h.group(1).strip()
            # TOC 锚点还原（Usage & Billing → usage--billing 无需精确，直接用标题文本）
            category = "" if title.lower() in ("plugins", "contents") else title
            continue
        m = _ENTRY_RE.match(line.strip())
        if m and m.group(1).lower() != "awesome-dsh-plugin/awesome-dsh-plugin":
            plugins.append({"repo": m.group(1), "desc": m.group(2).strip()[:160], "category": category or "Uncategorized"})
    return plugins


def _load_index(host: Any) -> tuple[list[dict] | None, str]:
    """缓存优先读索引；过期/缺失拉取。返回 (plugins, 状态说明)；失败 (None, 原因)."""
    path = _index_path(host)
    now = time.time()
    if path and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if now - data.get("fetched_at", 0) < INDEX_TTL_S:
                return data["plugins"], f"缓存（TTL 剩余 {int((INDEX_TTL_S - (now - data['fetched_at'])) / 3600)}h）"
        except Exception:  # noqa: BLE001 — 缓存损坏视为 miss
            pass
    try:
        plugins = parse_awesome(_fetch(AWESOME_README_URL))
    except Exception as e:  # noqa: BLE001 — 网络失败如实返回
        return None, f"索引不可用（{type(e).__name__}: {str(e)[:80]}）"
    if path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": now, "plugins": plugins}, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001 — 缓存写失败不影响功能
            pass
    return plugins, "已刷新"


def dsh_index_section(host: Any, top_n: int = 20) -> str:
    """skill_list 尾部追加段（失败时如实标注，本地技能段零回归）."""
    plugins, status = _load_index(host)
    if not plugins:
        return f"\n\n[DSH 插件索引] {status}"
    by_cat: dict[str, list[str]] = {}
    for p in plugins[:top_n]:
        by_cat.setdefault(p["category"], []).append(p["repo"])
    lines = [f"\n\n[DSH 插件索引] {len(plugins)} 插件（awesome-dsh-plugin 人工审核清单，{status}）"]
    lines.append(f"按分类前 {top_n} 条（完整清单用 skill_load dsh:owner/repo 查插件卡）:")
    for cat, repos in by_cat.items():
        lines.append(f"- {cat}: {', '.join(repos[:5])}")
    lines.append("安全边界: 索引只读；安装需走 dsh plugin add（官方 CLI），LFL 不执行插件代码。")
    return "\n".join(lines)


def run_dsh_skill_load(host: Any, repo: str) -> ToolResult:
    """skill_load dsh:owner/repo → 只读插件卡（README 摘要 + 桥接标注）."""
    repo = repo.strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", repo):
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[参数错误] dsh 插件名格式应为 owner/repo，收到 '{repo}'",
            tool_call_id="", tool_name="skill_load",
        )
    plugins, status = _load_index(host)
    meta = next((p for p in (plugins or []) if p["repo"].lower() == repo.lower()), None)
    if plugins is not None and meta is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[未收录] '{repo}' 不在 awesome-dsh-plugin 清单（{len(plugins)} 插件，{status}）。未收录≠不可用，可经 GitHub 自行核实后用 dsh_task 桥接。",
            tool_call_id="", tool_name="skill_load",
        )
    head = f"[DSH 插件卡] {repo}" + (f"\n分类: {meta['category']}\n描述: {meta['desc']}" if meta else "")
    snippet, err = "", ""
    try:
        readme = _fetch(f"https://raw.githubusercontent.com/{repo}/HEAD/README.md")
        snippet = re.sub(r"<[^>]+>", " ", readme[:README_SNIPPET_CHARS * 2])[:README_SNIPPET_CHARS]
    except Exception as e:  # noqa: BLE001 — README 拉取失败如实标注（卡仍可用）
        err = f"（README 拉取失败: {type(e).__name__}，卡内容仅含索引元数据）"
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"{head}\n来源: awesome-dsh-plugin 人工审核清单{err}\n"
            "执行方式: [需 dsh_task 桥接] 本工具只读不执行；代码类插件经 dsh plugin add 安装于 DSH 侧后由 dsh_task 调度。\n\n--- README 摘要 ---\n" + snippet
        ),
        tool_call_id="", tool_name="skill_load",
    )
