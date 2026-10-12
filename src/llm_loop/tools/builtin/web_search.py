"""基础工具: 网络搜索（M48，2026-08-12，借鉴 AnySearch 结构化结果设计）.

无 JS 渲染环境下实测可行的免费通道：Bing HTML（主）/ 百度 HTML（备）双后端互为降级。
返回结构化结果（title/url/snippet/source），不返回网页清单原始 HTML。

M48-C 垂直通道（2026-08-12，借鉴 AnySearch 多源直连思路，全部免 key 公开 API）：
channel=scholar 学术（OpenAlex/Crossref/PubMed 多源合并去重）；channel=code 代码（GitHub 免认证，
10 次/分钟限额如实提示）；channel=auto 按关键词路由。维基百科/arXiv 本机实测不通故未接入（诚实边界）。
"""

from __future__ import annotations

import contextlib
import contextvars
import html as _html
import json
import re
from urllib.parse import quote_plus

import httpx

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_evidence_shadow_enabled
from llm_loop.tools.source_recovery_contract import (
    SHARED_SOURCE_RECOVERY_CONTRACT,
    SourceRecoveryKind,
    source_recovery_guidance,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _search_bing(query: str, limit: int, timeout: float) -> list[dict]:
    """Bing HTML 端（302→cn.bing.com 跟随跳转后 200）.

    M49 增强: 按 b_algo 结果块解析，提取 <p> 摘要（实测可稳定拿到描述，
    供 LLM 预判相关性，减少盲目抓取）；无摘要时回退空串。
    """
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={min(limit * 2, 30)}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    resp.raise_for_status()
    # 按结果块解析（标题+摘要同块，避免跨块错配）
    blocks = re.findall(r'<li class="b_algo".*?</li>', resp.text, re.S)
    out: list[dict] = []
    for b in blocks:
        hm = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S | re.I)
        if not hm:
            continue
        u, t = hm.group(1), hm.group(2)
        title = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        snippet = ""
        for pm in re.findall(r'<p[^>]*>(.*?)</p>', b, re.S):
            cand = _html.unescape(re.sub(r"<[^>]+>", "", pm)).strip()
            if len(cand) > 30:  # 过滤日期/短碎片
                snippet = cand
                break
        if title and u.startswith("http"):
            out.append({"title": title, "url": u, "snippet": snippet, "source": "bing"})
        if len(out) >= limit:
            break
    if out:
        return out
    # 兼容无 b_algo 结构（旧测试/精简 HTML）：回退 h2 级解析（摘要为空）
    items = re.findall(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S | re.I)
    for u, t in items:
        title = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if title and u.startswith("http"):
            out.append({"title": title, "url": u, "snippet": "", "source": "bing"})
        if len(out) >= limit:
            break
    return out


def _search_baidu(query: str, limit: int, timeout: float) -> list[dict]:
    """百度 HTML 端（兜底，跳转链接保留原样并如实标注）."""
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers={"User-Agent": _UA})
    resp.raise_for_status()
    # 优先 result 块解析（含摘要）；无块时回退 h3 链接级解析（摘要为空）
    blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>.*?</div>\s*</div>', resp.text, re.S
    )
    out: list[dict] = []
    for b in blocks:
        hm = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S | re.I)
        if not hm:
            continue
        u, t = hm.group(1), hm.group(2)
        title = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        snippet = ""
        sm = re.search(r'class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</', b, re.S)
        if sm:
            snippet = _html.unescape(re.sub(r"<[^>]+>", "", sm.group(1))).strip()
        if title:
            out.append({"title": title, "url": u, "snippet": snippet, "source": "baidu(跳转链接)"})
        if len(out) >= limit:
            break
    if out:
        return out
    items = re.findall(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S | re.I)
    for u, t in items:
        title = _html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if title:
            out.append({"title": title, "url": u, "snippet": "", "source": "baidu(跳转链接)"})
        if len(out) >= limit:
            break
    return out


_JSON_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}


def _get_json(url: str, timeout: float) -> dict:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=_JSON_HEADERS)
    resp.raise_for_status()
    return json.loads(resp.text)


def _search_openalex(query: str, limit: int, timeout: float) -> list[dict]:
    """OpenAlex 学术（免 key，实测 170ms 响应、47 万级命中）."""
    data = _get_json(
        f"https://api.openalex.org/works?search={quote_plus(query)}&per-page={limit}", timeout
    )
    out = []
    for w in data.get("results", []):
        url = (w.get("primary_location") or {}).get("landing_page_url") or w.get("id", "")
        year = w.get("publication_year") or ""
        cited = w.get("cited_by_count")
        snippet = f"{year} 被引:{cited}" if year else ""
        out.append({"title": (w.get("title") or "").strip(), "url": url, "snippet": snippet, "source": "openalex"})
    return [r for r in out if r["title"]][:limit]


def _search_crossref(query: str, limit: int, timeout: float) -> list[dict]:
    """Crossref 学术（免 key，DOI 注册机构官方 API）."""
    data = _get_json(f"https://api.crossref.org/works?query={quote_plus(query)}&rows={limit}", timeout)
    out = []
    for w in (data.get("message") or {}).get("items", []):
        titles = w.get("title") or []
        doi = w.get("DOI", "")
        year = ""
        with contextlib.suppress(KeyError, IndexError, TypeError):
            year = str(w["issued"]["date-parts"][0][0])
        out.append({
            "title": titles[0].strip() if titles else "",
            "url": f"https://doi.org/{doi}" if doi else w.get("URL", ""),
            "snippet": year,
            "source": "crossref",
        })
    return [r for r in out if r["title"]][:limit]


def _search_pubmed(query: str, limit: int, timeout: float) -> list[dict]:
    """PubMed 生物医学（NCBI E-utilities 免 key）."""
    es = _get_json(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={quote_plus(query)}&retmode=json&retmax={limit}",
        timeout,
    )
    ids = (es.get("esearchresult") or {}).get("idlist", [])
    if not ids:
        return []
    summ = _get_json(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json",
        timeout,
    )
    result = summ.get("result") or {}
    out = []
    for uid in result.get("uids", []):
        item = result.get(uid) or {}
        out.append({
            "title": (item.get("title") or "").strip(),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
            "snippet": f"{item.get('source', '')} {item.get('pubdate', '')}".strip(),
            "source": "pubmed",
        })
    return [r for r in out if r["title"]][:limit]


def _search_github(query: str, limit: int, timeout: float) -> list[dict]:
    """GitHub 仓库（免认证 10 次/分钟，429 时如实报错）."""
    data = _get_json(
        f"https://api.github.com/search/repositories?q={quote_plus(query)}&per_page={limit}", timeout
    )
    out = []
    for w in data.get("items", []):
        stars = w.get("stargazers_count", 0)
        lang = w.get("language") or ""
        desc = (w.get("description") or "")[:100]
        out.append({
            "title": w.get("full_name", ""),
            "url": w.get("html_url", ""),
            "snippet": f"★{stars} {lang} {desc}".strip(),
            "source": "github",
        })
    return [r for r in out if r["title"]][:limit]


def _merge_dedupe(groups: list[list[dict]], limit: int) -> list[dict]:
    """多源结果合并去重（按 url/title），保持各源顺序交错."""
    seen: set[str] = set()
    out: list[dict] = []
    idx = 0
    while len(out) < limit:
        progressed = False
        for g in groups:
            if idx < len(g):
                progressed = True
                key = g[idx]["url"] or g[idx]["title"].lower()
                if key not in seen:
                    seen.add(key)
                    out.append(g[idx])
                    if len(out) >= limit:
                        break
        if not progressed:
            break
        idx += 1
    return out


_SCHOLAR_SOURCES = [("openalex", _search_openalex), ("crossref", _search_crossref), ("pubmed", _search_pubmed)]
_SCHOLAR_HINTS = ("论文", "文献", "研究", "学术", "paper", "study", "research", "arxiv", "doi")
_CODE_HINTS = ("github", "仓库", "源码", "开源", "repo", "library", "sdk")


def _route_channel(query: str) -> str:
    """auto 模式关键词路由（保守：无明确信号回 general，不误判）."""
    q = query.lower()
    if any(h in q for h in _CODE_HINTS):
        return "code"
    if any(h in q for h in _SCHOLAR_HINTS):
        return "scholar"
    return "general"


# EVO-20261010-528ab2f3: general 通道 HTML 后端的词典降级检测（人工已审批）。
# 现象: bing 会把 query 中的普通词（production/端/具 等）当词条解释返回，
# 表面"成功"但零有效信源，模型只能反复改写 query 自救。
# 此处只检测并在回执标注，结果本身完整保留（透传给模型决定是否改写重试）。
_DICT_HOSTS = frozenset({
    "dictionary.cambridge.org",
    "merriam-webster.com",
    "www.dictionary.com",
    "dict.cn",
    "www.iciba.com",
    "www.youdao.com",
    "www.vocabulary.com",
    "en.wiktionary.org",
    "zh.wiktionary.org",
})
_DICT_URL_MARKERS = ("/dict/",)  # bing/cn.bing 词典端点
_DEFINITIONAL_TITLE_MARKERS = (
    "释义", "是什么意思", "的翻译", "发音", "词典",
    "definition", "meaning", "dictionary", "pronunciation",
)
_QUERY_DICT_INTENT_MARKERS = (
    "意思", "翻译", "发音", "释义", "词典", "怎么读",
    "definition of", "meaning of", "how to pronounce",
)


def _dict_url_hit(result: dict) -> bool:
    """强特征: URL 指向词典端点/词典站（正常网页检索极少大量命中）."""
    url = (result.get("url") or "").lower()
    if any(m in url for m in _DICT_URL_MARKERS):
        return True
    host = url.split("//", 1)[-1].split("/", 1)[0]
    return any(host == h or host.endswith("." + h) for h in _DICT_HOSTS)


def _definitional_title_hit(result: dict) -> bool:
    """弱特征: 仅标题含释义词（正常文章标题也可能含 definition，不单独触发）."""
    title = (result.get("title") or "").lower()
    return any(m in title for m in _DEFINITIONAL_TITLE_MARKERS)


def _query_wants_dictionary(query: str) -> bool:
    """豁免: query 本身就是词条查询（用户意图，不算降级）."""
    q = query.lower()
    return any(m in q for m in _QUERY_DICT_INTENT_MARKERS)


def _detect_dictionary_fallback(results: list[dict]) -> bool:
    """词典型结果占比判定（保守阈值: 宁漏检不误伤正常结果）.

    strong = 词典 URL 特征; weak = 仅标题释义特征.
    触发: strong 占比 >= 0.6，或 strong>=1 且 (strong+weak) 占比 >= 0.8.
    """
    if not results:
        return False
    strong = sum(1 for r in results if _dict_url_hit(r))
    weak = sum(1 for r in results if not _dict_url_hit(r) and _definitional_title_hit(r))
    n = len(results)
    return strong / n >= 0.6 or (strong >= 1 and (strong + weak) / n >= 0.8)


_BACKENDS = [("bing", _search_bing), ("baidu", _search_baidu)]


class WebSearchTool:
    name = "web_search"
    description = (
        "网络搜索，返回结构化结果列表（标题/URL/来源）。何时用: 查找信息、找网页线索、验证外部事实。"
        "channel 可选: general 通用网页（默认，Bing/百度双后端）/ scholar 学术论文（OpenAlex+Crossref+PubMed 免 key 多源合并）"
        "/ code 代码仓库（GitHub 免认证）/ auto 按关键词自动路由。"
        "状态契约: 搜索结果默认完整返回；仅统一 ToolRegistry/Evidence 的真实输出硬上限可截断。"
        "何时不用: 已知确切 URL 时使用直接抓取能力；本地记录/档案检索使用对应的本地检索能力。"
        "失败对策: 后端被限流/超时会自动降级到备用后端并如实标注来源；全部失败如实返回原因。"
        "词典降级: 回执出现 degraded_backend=*_dictionary_fallback 标注时，结果疑似词条解释"
        "（仍完整保留），建议改写 query 后重试而非直接采信。"
        + SHARED_SOURCE_RECOVERY_CONTRACT
        + source_recovery_guidance(SourceRecoveryKind.WEB_SEARCH)
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词（单查询用；与 queries 二选一）"},
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：多个查询并发执行并聚合去重（≥2 个生效；多角度调研一次完成，EVO-20260820-14ccd432）",
            },
            "limit": {"type": "integer", "description": "每个查询返回结果条数（默认 5，最大 10）"},
            "channel": {
                "type": "string",
                "enum": ["general", "scholar", "code", "auto"],
                "description": "搜索通道：general 通用网页(默认) / scholar 学术论文 / code 代码仓库 / auto 关键词自动路由",
            },
        },
        "required": ["query"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)

    def _execute_vertical(self, query: str, limit: int, channel: str) -> ToolResult:
        """垂直通道执行：scholar 多源合并去重 / code 单源，单源失败降级其余源，全失败如实报."""
        sources = [("github", _search_github)] if channel == "code" else _SCHOLAR_SOURCES
        groups: list[list[dict]] = []
        errors: list[str] = []
        for name, fn in sources:
            try:
                groups.append(fn(query, limit, self._timeout_s))
            except Exception as exc:  # noqa: BLE001 — 单源失败降级其余源，如实记录
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        merged = _merge_dedupe(groups, limit)
        if not merged:
            detail = "; ".join(errors) if errors else "所有源均 0 条结果"
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[搜索失败] channel={channel} 无结果: {detail}",
                tool_call_id="",
                tool_name=self.name,
            )
        used = sorted({r["source"] for r in merged})
        lines = [f"[query] {query}  [channel] {channel}  [sources] {'+'.join(used)}  [count] {len(merged)}"]
        for i, r in enumerate(merged, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}  ({r['source']})")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
        if errors:
            lines.append(f"[降级记录] 部分源失败: {'; '.join(errors)}")
        content = "\n".join(lines)

        raw_observation = content if current_evidence_shadow_enabled.get() else None
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_observation,
        )

    def execute(self, **kwargs) -> ToolResult:
        # EVO-20260820-14ccd432: 多查询并发聚合（借鉴 DSH rc.8 web_search 并发查询）
        queries_raw = kwargs.get("queries")
        if isinstance(queries_raw, (list, tuple)):
            queries = [str(q).strip() for q in queries_raw if str(q) and str(q).strip()]
            if len(queries) >= 2:
                return self._execute_concurrent(queries, kwargs)
        query = str(kwargs.get("query", "")).strip()
        limit = min(max(int(kwargs.get("limit", 5) or 5), 1), 10)
        channel = str(kwargs.get("channel", "general") or "general").strip().lower()
        if channel == "auto":
            channel = _route_channel(query)
        if not query:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'query'（搜索关键词）",
                tool_call_id="",
                tool_name=self.name,
            )
        if channel in ("scholar", "code"):
            return self._execute_vertical(query, limit, channel)

        errors: list[str] = []
        for name, fn in _BACKENDS:
            try:
                results = fn(query, limit, self._timeout_s)
            except Exception as exc:  # noqa: BLE001 — 单后端失败降级下一后端，如实记录
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if results:
                lines = [f"[query] {query}  [backend] {name}  [count] {len(results)}"]
                # EVO-20261010-528ab2f3: 词典降级检测标注（结果不丢弃，透传给模型决定改写重试）
                if not _query_wants_dictionary(query) and _detect_dictionary_fallback(results):
                    lines.append(
                        f"[词典降级] degraded_backend={name}_dictionary_fallback: "
                        "结果疑似词条解释而非正常网页检索（零有效信源风险）。"
                        "建议改写 query（专有名词/品牌词开头，去掉孤立常用词）后重试; "
                        "本回执结果仍完整保留供参考。"
                    )
                for i, r in enumerate(results, 1):
                    lines.append(f"{i}. {r['title']}\n   {r['url']}  ({r['source']})")
                    if r["snippet"]:
                        lines.append(f"   {r['snippet']}")
                if errors:
                    lines.append(f"[降级记录] 前置后端失败: {'; '.join(errors)}")
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content="\n".join(lines),
                    tool_call_id="",
                    tool_name=self.name,
                )
            errors.append(f"{name}: 0 条结果")
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[搜索失败] 所有后端均不可用: {'; '.join(errors)}",
            tool_call_id="",
            tool_name=self.name,
        )

    # EVO-20260820-14ccd432: 多查询并发聚合（借鉴 DSH rc.8 web_search 并发查询）.
    # 一次调研 = 多个 query 并发 + 结果聚合去重，减少串行往返轮数。
    _CONCURRENT_MAX_WORKERS = 4

    def _execute_concurrent(self, queries: list[str], kwargs: dict) -> ToolResult:
        """并发执行多个独立查询并聚合（块级去重 + 如实标注失败）.

        每个查询独立走单查询路径（general/scholar/code 各自路由），
        ThreadPoolExecutor 并发（网络 IO 为主，无共享可变状态）；
        聚合按内容块去重（相同块只留一次），失败查询如实列出不吞错。
        """
        import concurrent.futures

        limit = min(max(int(kwargs.get("limit", 5) or 5), 1), 10)
        channel = str(kwargs.get("channel", "general") or "general").strip().lower()

        def _one(q: str) -> tuple[str, ToolResult]:
            ch = channel
            if ch == "auto":
                ch = _route_channel(q)
            return q, self.execute(query=q, limit=limit, channel=ch)

        workers = min(len(queries), self._CONCURRENT_MAX_WORKERS)
        ok: list[tuple[str, str]] = []
        failed: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(contextvars.copy_context().run, _one, q): q for q in queries}
            for fut in concurrent.futures.as_completed(futures):
                q, r = fut.result()
                if r.status == ToolResultStatus.SUCCESS:
                    ok.append((r.content, r.raw_observation or r.content))
                else:
                    failed.append(f"[query] {q} -> {r.content}")

        # 块级去重（保持首次出现顺序）
        seen: set[str] = set()
        blocks: list[str] = []
        raw_blocks: list[str] = []
        for visible, raw in ok:
            if visible not in seen:
                seen.add(visible)
                blocks.append(visible)
                raw_blocks.append(raw)
        head = f"[web_search 并发] 查询 {len(queries)} 个，成功 {len(ok)}，聚合去重 {len(blocks)} 块"
        lines = [head, ""] + blocks
        raw_lines = [head, ""] + raw_blocks
        if failed:
            lines += ["", "[失败查询（如实标注）]"] + failed
            raw_lines += ["", "[失败查询（如实标注）]"] + failed
        if not blocks:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="\n".join(lines),
                tool_call_id="",
                tool_name=self.name,
            )
        raw_content = "\n".join(raw_lines)

        raw_observation = raw_content if current_evidence_shadow_enabled.get() else None
        content = "\n".join(lines)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_observation,
        )
