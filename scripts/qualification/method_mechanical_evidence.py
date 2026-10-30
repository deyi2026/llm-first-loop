"""Mechanical evidence batch collector for Method cards (proposal-only).

Governance basis: docs/governance/card-lifecycle.md R3-bis, "批量处置的纪律
(2026-10-30 修订：证据分流，使用优先)" — the mechanical-evidence channel
(事实轴): a card can be batch-invalidated on independently re-runnable facts
(URL 404 sampled twice >=10 minutes apart, a missing local path/file the card
anchors on, a missing tool), each judgement carrying its own 应拦 tests.

Contract (proposal-only, enforced):
- This script NEVER writes anything under the methods dir it reads (data/methods
  by default) and never imports or constructs the MethodStore. Its only writes
  are the two manifest artifacts plus a URL-sample state file, and each of those
  paths is refused if it resolves inside the methods dir (see
  ``_assert_outside_methods_dir``; pinned by tests).
- Every check records evidence as the exact command that produced it, so any
  finding can be re-run by a human: path checks execute ``test -e <path>`` from
  the repo root; URL checks execute a ``curl`` one-liner. Evidence IS the
  implementation, not a description of it.

Judgement layers (deliberately asymmetric — a check may exonerate cheaply but
may convict only on its strongest evidence):
- local_path / frontmatter freshness_refs (author-declared freshness anchor):
  missing -> verdict=fail, ready_to_land=true (deterministic, single run).
- local_path / body mentions and file: evidence refs: missing -> manual_review
  (a prose mention is not an operational anchor; a human decides whether it is
  load-bearing). Present -> pass (informational).
- tool_existence: catalog = registry.py::_COMPACT_TOOL_DESCRIPTIONS (static,
  extracted by AST — no runtime import). Mentioned name in catalog -> pass;
  not in catalog -> manual_review (could be a shell command or an external
  tool; the catalog only covers this workspace's agent tools, so absence is
  not proof of staleness). Tools never convict on their own.
- url: two-phase sampling. 2xx/3xx -> pass; 404 once -> pending_sample2;
  404 twice with gap >= 600s -> fail (ready_to_land=true); anything else
  (403/429/5xx, DNS failure, timeout, curl error) -> no_verdict. Transient
  network trouble is never evidence.
- code_conflict: not mechanically generalisable — not attempted; every card
  carries an explicit "needs human" field instead.

Usage:
    python3 scripts/qualification/method_mechanical_evidence.py collect \
        --methods-dir data/methods --select usage-candidates \
        --url-phase sample1 \
        --out-json docs/governance/card-audit/<date>-mechanical-evidence.json \
        --out-md    docs/governance/card-audit/<date>-mechanical-evidence.md

    python3 scripts/qualification/method_mechanical_evidence.py queue \
        --methods-dir data/methods \
        --out docs/governance/method-review-queue-<date>.md

    # sample2 later (>=10 min after a recorded 404 sample1; same --state file):
    ... collect ... --url-phase sample2
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Same integrity 口径 as the store's read side (llm_loop/use_ledger.py):
# lines whose embedded integrity credential no longer matches are invisible to
# statistics; legacy lines without a credential remain readable.
try:
    from llm_loop.use_ledger import line_integrity_matches
except Exception:  # noqa: BLE001 — read-side util unavailable must not block read-only work
    def line_integrity_matches(entry: dict) -> bool:  # type: ignore[misc]
        return True

VERDICTS = ("fail", "pass", "no_verdict", "pending_sample2", "manual_review")
CHECK_TYPES = ("local_path", "tool_existence", "url", "code_conflict")

SAMPLE2_MIN_GAP_S = 600  # governance: 同 URL 两次采样间隔 >= 10 分钟
_REGISTRY_CATALOG = ("src/llm_loop/tools/registry.py", "_COMPACT_TOOL_DESCRIPTIONS")

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_NAMESPACED_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:")
_REPO_TOP_DIRS = ("src", "scripts", "docs", "tests", "evals")
_BODY_PATH_RE = re.compile(
    r"(?<![\w./\-])((?:src|scripts|docs|tests|evals)/"
    r"[A-Za-z0-9_][A-Za-z0-9_./\-]{1,120}[A-Za-z0-9_\-])"
)
_URL_RE = re.compile(r"https?://[^\s<>\"'`，。；、）】]+")
_TOOL_TOKEN_RE = re.compile(r"`([a-z][a-z0-9_\-]{2,40})`")
_PLACEHOLDER_HOSTS = {
    "example.com", "example.org", "example.net", "localhost",
    "127.0.0.1", "0.0.0.0", "::1",
}
_PLACEHOLDER_SUFFIXES = (".invalid", ".test", ".local", ".example")


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _parse_ts(ts: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(ts).strip())
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except (ValueError, TypeError):
        return None


def _frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _body(text: str) -> str:
    match = _FRONTMATTER_RE.match(text)
    return text[match.end():].strip() if match else text.strip()


def _split_refs(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


# ---------------------------------------------------------------- selection


def usage_index(methods_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Group valid usage-ledger entries by method_ref (store read 口径)."""
    path = methods_dir / "usage.jsonl"
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not path.is_file():
        return grouped, "no_ledger"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or not line_integrity_matches(value):
            continue
        ref = str(value.get("method_ref", "")).strip()
        if ref:
            grouped.setdefault(ref, []).append(value)
    return grouped, "ok"


def load_card(methods_dir: Path, ref: str) -> dict[str, Any] | None:
    method_id = ref.split(":", 1)[-1] if ref.startswith("method:") else ref
    card_path = methods_dir / method_id / "METHOD.md"
    if not card_path.is_file():
        return None
    text = card_path.read_text(encoding="utf-8", errors="replace")
    meta = _frontmatter(text)
    return {
        "method_ref": f"method:{meta.get('method_id') or method_id}",
        "method_id": meta.get("method_id") or method_id,
        "name": meta.get("name") or method_id,
        "status": meta.get("status", ""),
        "freshness_refs": meta.get("freshness_refs", ""),
        "evidence_refs": meta.get("evidence_refs", ""),
        "text": text,
        "body": _body(text),
        "path": str(card_path),
    }


def usage_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = Counter(str(e.get("decision", "") or "unknown") for e in entries)
    last_ts = max((str(e.get("ts", "")) for e in entries), default="")
    return {
        "entries": len(entries),
        "decision_counts": dict(sorted(decisions.items())),
        "last_used_ts": last_ts,
    }


def select_usage_candidates(
    methods_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """usage 账本非空 且 当前 status=candidate（R3-bis 口径）."""
    grouped, _ = usage_index(methods_dir)
    cards: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for ref in sorted(grouped):
        entries = grouped[ref]
        card = load_card(methods_dir, ref)
        if card is None:
            skipped.append({"method_ref": ref, "reason": "no_card_dir"})
            continue
        if card["status"] != "candidate":
            skipped.append({"method_ref": ref, "reason": f"status={card['status']}"})
            continue
        card["usage"] = usage_summary(entries)
        cards.append(card)
    return cards, skipped


# ------------------------------------------------------- assertion extraction


def extract_path_claims(card: dict[str, Any]) -> list[dict[str, str]]:
    """Repo-relative path claims, layered by how strongly the card anchors on them."""
    claims: list[dict[str, str]] = []

    def add(path: str, source: str, severity: str) -> None:
        path = path.strip().strip("`")
        if not path or ".." in path or path.startswith("/"):
            return
        if not any(path.startswith(top + "/") for top in _REPO_TOP_DIRS):
            return
        if not any(c["path"] == path and c["source"] == source for c in claims):
            claims.append({"path": path, "source": source, "severity": severity})

    for ref in _split_refs(card.get("freshness_refs", "")):
        if _NAMESPACED_REF_RE.match(ref):
            continue  # learning:/episode:/... namespaced refs are not file paths
        if "/" in ref:
            add(ref, "frontmatter.freshness_refs", "anchor")
    for ref in _split_refs(card.get("evidence_refs", "")):
        if ref.startswith("file:"):
            add(ref[len("file:"):], "frontmatter.evidence_refs[file:]", "provenance")
    seen_body: set[str] = set()
    for match in _BODY_PATH_RE.findall(card.get("body", "")):
        if match not in seen_body:
            seen_body.add(match)
            add(match, "body", "mention")
    return claims


def extract_urls(card: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for raw in _URL_RE.findall(card.get("text", "")):
        url = raw.rstrip(".,;:!?)")
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            continue
        if not host:
            continue
        if host in _PLACEHOLDER_HOSTS or host.endswith(_PLACEHOLDER_SUFFIXES):
            continue  # placeholder/documentation host, not a claim about the world
        if url not in urls:
            urls.append(url)
    return urls


def extract_tool_tokens(card: dict[str, Any]) -> list[str]:
    """Backticked identifier tokens only — an unmarked prose identifier is not a
    claim about a named tool, so it is deliberately not extracted."""
    seen: list[str] = []
    for token in _TOOL_TOKEN_RE.findall(card.get("body", "")):
        if token not in seen:
            seen.append(token)
    return seen


def registry_tool_names(repo_root: Path) -> tuple[set[str] | None, str]:
    """Static tool catalog (AST + module stems; no runtime import).

    Two static sources, both mechanically checkable:
    1. registry.py :: _COMPACT_TOOL_DESCRIPTIONS — the compact description dict;
    2. src/llm_loop/tools/builtin/*.py module stems (house convention: one
       builtin tool per module, module name == tool name).

    Known blind spot, stated up front: knowledge-plane tools registered at
    runtime (e.g. method_manage) appear in neither static source. That is why
    "not in catalog" is manual_review, never fail.
    """
    source_path = repo_root / _REGISTRY_CATALOG[0]
    names: set[str] = set()
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None, f"{_REGISTRY_CATALOG[0]} unreadable"
    for node in tree.body:
        names_hits: list[str] = []
        values: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            names_hits = [t.id for t in node.targets if isinstance(t, ast.Name)]
            values = [node.value]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names_hits = [node.target.id]
            if node.value is not None:
                values = [node.value]
        else:
            continue
        if _REGISTRY_CATALOG[1] not in names_hits:
            continue
        for value in values:
            if isinstance(value, ast.Dict):
                names |= {
                    key.value
                    for key in value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
    if not names:
        return None, f"{_REGISTRY_CATALOG[1]} not found in {_REGISTRY_CATALOG[0]}"
    builtin_dir = repo_root / "src" / "llm_loop" / "tools" / "builtin"
    stems: set[str] = set()
    if builtin_dir.is_dir():
        stems = {p.stem for p in builtin_dir.glob("*.py") if p.stem != "__init__"}
    names |= stems
    return names, (
        f"{_REGISTRY_CATALOG[0]} :: {_REGISTRY_CATALOG[1]}（{len(names - stems)} 项）"
        f" + src/llm_loop/tools/builtin/*.py 模块名（{len(stems)} 项）；"
        "运行时动态注册的工具（如 method_manage）不在静态清单内"
    )


# ------------------------------------------------------------------- checks


def path_checker_default(path: str, repo_root: Path) -> dict[str, Any]:
    """Deterministic single run (governance: 本地路径确定性单次成立).

    Evidence command == replay command == implementation.
    """
    command = f"test -e {shlex.quote(path)}"
    try:
        proc = subprocess.run(
            ["/bin/test", "-e", path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        exit_code = proc.returncode
        stderr = (proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": command,
            "cwd": str(repo_root),
            "exit_code": -1,
            "output_excerpt": f"check_failed: {exc}",
            "ts": _now_iso(),
            "exists": None,
        }
    return {
        "command": command,
        "cwd": str(repo_root),
        "exit_code": exit_code,
        "output_excerpt": f"exit={exit_code}" + (f" stderr={stderr[:120]}" if stderr else ""),
        "ts": _now_iso(),
        "exists": exit_code == 0,
    }


def url_checker_default(url: str, timeout_s: int) -> dict[str, Any]:
    """One curl sample. Any transport-level trouble is transient, never evidence."""
    command = (
        f"curl -sS -o /dev/null -w '%{{http_code}}' "
        f"--max-time {timeout_s} --connect-timeout 10 {shlex.quote(url)}"
    )
    try:
        proc = subprocess.run(
            [
                "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
                "--max-time", str(timeout_s), "--connect-timeout", "10", url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s + 10,
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        http_code: int | None = None
        if proc.returncode == 0 and stdout.isdigit():
            http_code = int(stdout)
        transient = proc.returncode != 0 or http_code in (None, 0)
        return {
            "command": command,
            "http_code": http_code,
            "exit_code": proc.returncode,
            "output_excerpt": f"http_code={stdout or '-'} exit={proc.returncode}"
            + (f" stderr={stderr[:120]}" if stderr else ""),
            "transient": transient,
            "ts": _now_iso(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": command,
            "http_code": None,
            "exit_code": -1,
            "output_excerpt": f"check_failed: {exc}",
            "transient": True,
            "ts": _now_iso(),
        }


def judge_url(samples: list[dict[str, Any]], *, min_gap_s: int = SAMPLE2_MIN_GAP_S) -> tuple[str, str]:
    """Pure judgement over recorded samples (R3 事实轴 URL 规则).

    2xx/3xx -> pass; 404x2 with gap >= min_gap_s -> fail; one 404 ->
    pending_sample2; everything else (incl. transport errors) -> no_verdict.
    """
    live = [
        s for s in samples
        if isinstance(s.get("http_code"), int) and 200 <= s["http_code"] < 400
    ]
    if live:
        return "pass", "存在 2xx/3xx 样本：锚点存活，不构成证据"
    not_found = [s for s in samples if s.get("http_code") == 404]
    if len(not_found) >= 2:
        first_ts = _parse_ts(not_found[0].get("ts", ""))
        last_ts = _parse_ts(not_found[-1].get("ts", ""))
        if first_ts is None or last_ts is None:
            return "no_verdict", "404 样本缺时间戳，无法核间隔"
        gap_s = int((last_ts - first_ts).total_seconds())
        if gap_s >= min_gap_s:
            return "fail", f"404×2，间隔 {gap_s}s ≥ {min_gap_s}s（双采样成立）"
        return "pending_sample2", f"两次 404 间隔 {gap_s}s < {min_gap_s}s，不采信，等待合格二次采样"
    if not_found:
        return "pending_sample2", "仅一次 404 采样（sample1），等待 sample2"
    if samples:
        return "no_verdict", "瞬态网络错误/非 404 异常态：一律无判定，不算证据"
    return "no_verdict", "无样本"


# ---------------------------------------------------------------- manifest


def _rollback(method_ref: str, manifest_path: str) -> dict[str, list[str]]:
    return {
        "apply": [
            f"method_manage(action='record_qualification', method_ref='{method_ref}', "
            f"verdict='fail', mechanism='fail', task_benefit='not_evaluated', "
            f"promotion='fail', note='<机械证据：见 manifest 内 claim>', "
            f"evidence_refs=['{manifest_path}'])  # 由持有真实 episode 的父会话执行",
            f"method_manage(action='refine', method_ref='{method_ref}', transition='invalidate')",
        ],
        "undo": [
            f"method_manage(action='refine', method_ref='{method_ref}', transition='reopen')  "
            "# 治理文本称 restore/reopen；store 侧 reopen 永远可用（R3）",
        ],
    }


def _finding(
    *,
    method_ref: str,
    check_type: str,
    claim_text: str,
    claim_location: str,
    replay_command: str,
    verdict: str,
    evidence: dict[str, Any] | None,
    note: str,
    manifest_path: str,
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict not in vocabulary: {verdict}")
    return {
        "method_ref": method_ref,
        "check_type": check_type,
        "claim": {
            "text": claim_text,
            "location": claim_location,
            "replay_command": replay_command,
        },
        "verdict": verdict,
        "evidence": evidence or {"command": "", "output_excerpt": "", "ts": ""},
        "note": note,
        "rollback": _rollback(method_ref, manifest_path),
        "ready_to_land": verdict == "fail",
    }


def _assert_outside_methods_dir(target: Path, methods_dir: Path) -> None:
    resolved = Path(target).resolve()
    root = Path(methods_dir).resolve()
    if resolved == root or root in resolved.parents:
        raise SystemExit(
            f"refusing to write inside the methods dir (proposal-only): {resolved}"
        )


def _load_state(state_path: Path) -> dict[str, Any]:
    if state_path.is_file():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("url_samples"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"url_samples": {}}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now_iso()
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_collect(
    methods_dir: Path,
    *,
    select: str = "usage-candidates",
    methods: str = "",
    out_json: Path,
    out_md: Path,
    state_path: Path | None = None,
    url_phase: str = "sample1",
    url_timeout_s: int = 20,
    repo_root: Path | None = None,
    url_checker: Callable[[str, int], dict[str, Any]] | None = None,
    path_checker: Callable[[str, Path], dict[str, Any]] | None = None,
    now_fn: Callable[[], str] = _now_iso,
) -> dict[str, Any]:
    """Read cards, run mechanical checks, write the proposal-only manifest.

    Injected ``url_checker``/``path_checker``/``now_fn`` exist so tests can pin
    judgement behaviour without touching the network or the wall clock.
    """
    methods_dir = Path(methods_dir)
    repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    url_checker = url_checker or url_checker_default
    path_checker = path_checker or path_checker_default
    if state_path is None:
        state_path = out_json.parent / (out_json.stem + ".url-samples.json")
    for target in (out_json, out_md, state_path):
        _assert_outside_methods_dir(Path(target), methods_dir)

    skipped: list[dict[str, str]] = []
    if select == "usage-candidates":
        cards, skipped = select_usage_candidates(methods_dir)
    else:
        cards = []
        grouped, _ = usage_index(methods_dir)
        for name in [m.strip() for m in methods.split(",") if m.strip()]:
            card = load_card(methods_dir, name)
            if card is None:
                skipped.append({"method_ref": name, "reason": "no_card_dir"})
                continue
            card["usage"] = usage_summary(grouped.get(card["method_ref"], []))
            cards.append(card)

    catalog, catalog_source = registry_tool_names(repo_root)
    state = _load_state(state_path)
    ran_at = now_fn()

    cards_out: list[dict[str, Any]] = []
    findings_flat: list[dict[str, Any]] = []
    for card in cards:
        findings: list[dict[str, Any]] = []

        # --- local_path ---------------------------------------------------
        for claim in extract_path_claims(card):
            result = path_checker(claim["path"], repo_root)
            replay = f"cd {shlex.quote(str(repo_root))} && {result['command']}"
            if result.get("exists") is True:
                verdict, note = "pass", "路径存在（锚点/引用完好，信息性）"
            elif result.get("exists") is False:
                if claim["severity"] == "anchor":
                    verdict = "fail"
                    note = "作者声明的 freshness 锚点不存在：卡依赖的工件已消失"
                else:
                    verdict = "manual_review"
                    note = (
                        "路径不存在，但正文提及/file: 证据引用不等于操作性锚点，"
                        "是否 load-bearing 留人工判断（不硬做定罪）"
                    )
            else:
                verdict, note = "no_verdict", "检查本身失败（工具异常），无判定"
            findings.append(
                _finding(
                    method_ref=card["method_ref"],
                    check_type="local_path",
                    claim_text=(
                        f"[{claim['severity']}] {claim['source']} 声明仓库路径 "
                        f"{claim['path']} 存在"
                    ),
                    claim_location=claim["source"],
                    replay_command=replay,
                    verdict=verdict,
                    evidence=result,
                    note=note,
                    manifest_path=str(out_json),
                )
            )

        # --- tool_existence -----------------------------------------------
        for token in extract_tool_tokens(card):
            if catalog is None:
                verdict, note = (
                    "manual_review",
                    f"注册表清单不可读（{catalog_source}）：不可机械化，留人工",
                )
            elif token in catalog:
                verdict, note = "pass", f"在工具注册表中（{catalog_source}）"
            else:
                verdict = "manual_review"
                note = (
                    "不在本仓工具注册表；可能是 shell 命令或外部工具"
                    "（注册表只覆盖 workspace agent 工具），无法机械化定罪，留人工"
                )
            findings.append(
                _finding(
                    method_ref=card["method_ref"],
                    check_type="tool_existence",
                    claim_text=f"正文以反引号提及工具/命令 `{token}`",
                    claim_location="body",
                    replay_command=(
                        f"grep -n {shlex.quote('`' + token + '`')} {shlex.quote(card['path'])}"
                    ),
                    verdict=verdict,
                    evidence=None,
                    note=note,
                    manifest_path=str(out_json),
                )
            )

        # --- url ------------------------------------------------------------
        for url in extract_urls(card):
            record = state["url_samples"].setdefault(url, {"samples": []})
            samples: list[dict[str, Any]] = record["samples"]
            blocked_note = ""
            if url_phase == "sample1":
                if not samples:
                    samples.append(url_checker(url, url_timeout_s))
            elif url_phase == "sample2":
                prior_404 = [s for s in samples if s.get("http_code") == 404]
                if not prior_404:
                    blocked_note = "无 404 前置采样，sample2 无对象"
                else:
                    last_ts = _parse_ts(prior_404[-1].get("ts", ""))
                    now_dt = _parse_ts(ran_at)
                    gap = (
                        int((now_dt - last_ts).total_seconds())
                        if last_ts and now_dt
                        else None
                    )
                    if gap is None or gap < SAMPLE2_MIN_GAP_S:
                        blocked_note = (
                            f"距上次 404 采样 {gap if gap is not None else '?'}s "
                            f"< {SAMPLE2_MIN_GAP_S}s：间隔未满，本次不采样"
                        )
                    else:
                        samples.append(url_checker(url, url_timeout_s))
            elif url_phase != "skip":
                raise SystemExit(f"unknown url_phase: {url_phase}")

            verdict, judge_note = judge_url(samples)
            if url_phase == "skip":
                verdict, judge_note = "no_verdict", "url_phase=skip：未采样"
            if blocked_note:
                judge_note = f"{judge_note}；{blocked_note}"
            latest = samples[-1] if samples else None
            findings.append(
                _finding(
                    method_ref=card["method_ref"],
                    check_type="url",
                    claim_text=f"正文含外部 URL {url}（死链即事实性失锚）",
                    claim_location="card text",
                    replay_command=(latest or {}).get("command", "")
                    or (
                        f"curl -sS -o /dev/null -w '%{{http_code}}' "
                        f"--max-time {url_timeout_s} {shlex.quote(url)}"
                    ),
                    verdict=verdict,
                    evidence=latest,
                    note=judge_note,
                    manifest_path=str(out_json),
                )
            )

        cards_out.append(
            {
                "method_ref": card["method_ref"],
                "name": card["name"],
                "status": card["status"],
                "usage": card.get("usage", {}),
                "findings": findings,
                "code_conflict": {
                    "check_type": "code_conflict",
                    "verdict": "manual_review",
                    "note": "代码冲突摘录不可通用机械化：不硬做，需人工对照卡正文与现行代码",
                },
                "ready_to_land": any(f["ready_to_land"] for f in findings),
            }
        )
        findings_flat.extend(findings)

    by_verdict = Counter(f["verdict"] for f in findings_flat)
    by_type: dict[str, Counter] = {}
    for f in findings_flat:
        by_type.setdefault(f["check_type"], Counter())[f["verdict"]] += 1
    payload = {
        "generated_by": "scripts/qualification/method_mechanical_evidence.py collect",
        "ran_at": ran_at,
        "governance_basis": "docs/governance/card-lifecycle.md R3-bis（2026-10-30 修订：证据分流，使用优先）",
        "proposal_only": True,
        "never_writes": [
            f"{methods_dir}（含全部卡文件与 usage.jsonl）",
            "store（本脚本不 import、不构造 MethodStore）",
        ],
        "writes_performed": [str(out_json), str(out_md), str(state_path)],
        "selection": {
            "mode": select,
            "criteria": "usage 账本非空 且 status=candidate"
            if select == "usage-candidates"
            else "显式卡清单",
            "cards": len(cards_out),
            "skipped": skipped,
        },
        "tool_catalog": {
            "source": catalog_source,
            "names": len(catalog) if catalog else 0,
            "available": catalog is not None,
        },
        "url_sampling": {
            "phase": url_phase,
            "min_gap_s": SAMPLE2_MIN_GAP_S,
            "state_file": str(state_path),
            "pending_sample2": sum(
                1 for c in cards_out for f in c["findings"]
                if f["verdict"] == "pending_sample2"
            ),
        },
        "stats": {
            "findings_total": len(findings_flat),
            "by_verdict": dict(sorted(by_verdict.items())),
            "by_check_type": {k: dict(sorted(v.items())) for k, v in sorted(by_type.items())},
            "landable_findings": sum(1 for f in findings_flat if f["ready_to_land"]),
            "cards_ready_to_land": sum(1 for c in cards_out if c["ready_to_land"]),
        },
        "cards": cards_out,
        "notes": [
            "本 manifest 是 proposal：不写入任何 store/卡文件；落地动作由持有真实 episode 的父会话按 rollback.apply 执行。",
            "verdict=fail 的依据全部可复跑：evidence.command 即产出该判定的原始命令。",
            "瞬态网络错误与检查失败一律 no_verdict，不算证据（R3 事实轴）。",
        ],
    }

    out_json = Path(out_json)
    out_md = Path(out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    _assert_outside_methods_dir(out_json, methods_dir)
    _assert_outside_methods_dir(out_md, methods_dir)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_state(Path(state_path), state)
    out_md.write_text(render_md(payload), encoding="utf-8")
    return payload


# ------------------------------------------------------------------- markdown


def _md_escape(text: str, limit: int = 160) -> str:
    text = str(text).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


_VERDICT_LABEL = {
    "fail": "fail（机械证据成立）",
    "pass": "pass（断言成立，非证据）",
    "no_verdict": "no_verdict（无判定）",
    "pending_sample2": "pending_sample2（待二次采样）",
    "manual_review": "manual_review（需人工）",
}


def render_md(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 机械证据批采 manifest（proposal-only）")
    lines.append("")
    lines.append(f"- 生成：{payload['generated_by']}，ran_at：{payload['ran_at']}")
    lines.append(f"- 治理依据：{payload['governance_basis']}")
    lines.append("- **本 manifest 不写库、不改卡**：脚本对 methods 目录无任何写路径；落地与回滚均由父会话执行。")
    lines.append(
        f"- 选择口径：{payload['selection']['criteria']}；卡数：{payload['selection']['cards']}"
    )
    lines.append(
        f"- 工具清单来源：{payload['tool_catalog']['source']}"
        f"（{payload['tool_catalog']['names']} 项）"
    )
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    stats = payload["stats"]
    lines.append(f"- findings：{stats['findings_total']} 条；判定分布：{stats['by_verdict']}")
    for check_type, dist in stats["by_check_type"].items():
        lines.append(f"  - {check_type}: {dist}")
    lines.append(
        f"- ready_to_land（verdict=fail 且证据可复跑）：{stats['landable_findings']} 条 / "
        f"{stats['cards_ready_to_land']} 张卡"
    )
    lines.append(
        f"- URL 待二次采样：{payload['url_sampling']['pending_sample2']} 条"
        f"（间隔阈值 {payload['url_sampling']['min_gap_s']}s，"
        f"状态文件 {payload['url_sampling']['state_file']}）"
    )
    lines.append("")
    lines.append("## 逐卡发现")
    for card in payload["cards"]:
        lines.append("")
        usage = card.get("usage") or {}
        usage_txt = (
            f"usage {usage.get('entries', 0)} 条 {usage.get('decision_counts', {})}，"
            f"最近 {usage.get('last_used_ts', '-')}"
            if usage
            else "usage 0 条"
        )
        lines.append(
            f"### {card['method_ref']}（{card['name']}，{card['status']}；{usage_txt}）"
        )
        lines.append("")
        if not card["findings"]:
            lines.append("- 无可机械核验断言（无 freshness_refs/正文仓库路径/URL/反引号工具提及）。")
        else:
            lines.append("| 检查类型 | 判定 | claim | 证据（命令 → 输出） | ready_to_land |")
            lines.append("|---|---|---|---|---|")
            for f in card["findings"]:
                ev = f["evidence"] or {}
                if ev.get("command"):
                    ev_txt = (
                        f"`{_md_escape(ev.get('command', ''), 120)}` → "
                        f"`{_md_escape(ev.get('output_excerpt', ''), 80)}`"
                    )
                else:
                    ev_txt = "（成员检查/人工项，无命令输出）"
                lines.append(
                    f"| {f['check_type']} | {_VERDICT_LABEL.get(f['verdict'], f['verdict'])} "
                    f"| {_md_escape(f['claim']['text'])} | {ev_txt} "
                    f"| {str(f['ready_to_land']).lower()} |"
                )
        lines.append("")
        lines.append(f"- code_conflict：{card['code_conflict']['note']}")
        if card["ready_to_land"]:
            lines.append("- 回滚路径：见 JSON manifest 该卡 findings[].rollback（invalidate → reopen）。")
    lines.append("")
    lines.append("## 应拦测试")
    lines.append("")
    lines.append(
        "每类判定的应拦输入实测见 `tests/test_method_mechanical_evidence.py`："
        "URL 200 不判 fail、瞬态网络错误不判 fail、单次 404 不得 ready_to_land、"
        "存在的路径不得标记不存在、正文提及缺失不硬定罪、两次 404 间隔不足不采信、"
        "对 methods 目录零写入、输出路径落在 methods 目录内直接拒绝。"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- queue


def run_queue(methods_dir: Path, out_path: Path) -> dict[str, Any]:
    """Emit the usage-candidate review queue markdown (proposal-only artifact)."""
    methods_dir = Path(methods_dir)
    cards, skipped = select_usage_candidates(methods_dir)
    out_path = Path(out_path)
    _assert_outside_methods_dir(out_path, methods_dir)
    rows = sorted(
        cards,
        key=lambda c: (-c["usage"]["entries"], c["usage"]["last_used_ts"], c["method_ref"]),
    )
    lines = [
        "# Method 独立评审/机械通道队列 — 2026-10-30",
        "",
        "口径（card-lifecycle.md R3-bis，2026-10-30 修订）：usage 账本非空且 status=candidate。",
        "生成命令：`python3 scripts/qualification/method_mechanical_evidence.py queue "
        "--methods-dir data/methods --out docs/governance/method-review-queue-20261030.md`"
        "（proposal-only，不写 data/methods）。",
        "",
        f"- 卡数：{len(cards)}；账本引用但无卡目录/非 candidate 的 ref：{len(skipped)}（见文末）",
        "",
        "| method_ref | 标题 | usage 计数 | decision 分布 | 最近使用 |",
        "|---|---|---|---|---|",
    ]
    for card in rows:
        usage = card["usage"]
        decisions = ", ".join(f"{k}×{v}" for k, v in usage["decision_counts"].items()) or "-"
        lines.append(
            f"| `{card['method_ref']}` | {_md_escape(card['name'], 80)} | {usage['entries']} "
            f"| {decisions} | {usage['last_used_ts'] or '-'} |"
        )
    if skipped:
        lines.append("")
        lines.append("## 未入队引用（账本有、卡不在或非 candidate）")
        lines.append("")
        for item in skipped:
            lines.append(f"- `{item['method_ref']}`：{item['reason']}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"cards": len(cards), "skipped": len(skipped), "out": str(out_path)}


# ----------------------------------------------------------------------- cli


def cmd_collect(args: argparse.Namespace) -> int:
    payload = run_collect(
        Path(args.methods_dir),
        select=args.select,
        methods=args.methods,
        out_json=Path(args.out_json),
        out_md=Path(args.out_md),
        state_path=Path(args.state) if args.state else None,
        url_phase=args.url_phase,
        url_timeout_s=args.url_timeout,
    )
    print(
        json.dumps(
            {
                "cards": payload["selection"]["cards"],
                "findings": payload["stats"]["findings_total"],
                "by_verdict": payload["stats"]["by_verdict"],
                "landable": payload["stats"]["landable_findings"],
                "url_pending_sample2": payload["url_sampling"]["pending_sample2"],
                "out": payload["writes_performed"][0],
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    result = run_queue(Path(args.methods_dir), Path(args.out))
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mechanical evidence collector (proposal-only)")
    sub = parser.add_subparsers(dest="stage", required=True)

    p_collect = sub.add_parser("collect", help="run mechanical checks over a card set, emit proposal manifest")
    p_collect.add_argument("--methods-dir", default="data/methods")
    p_collect.add_argument("--select", default="usage-candidates", choices=["usage-candidates", "methods"])
    p_collect.add_argument("--methods", default="", help="comma-separated refs/dir names (with --select methods)")
    p_collect.add_argument("--out-json", required=True)
    p_collect.add_argument("--out-md", required=True)
    p_collect.add_argument("--state", default="", help="URL sample state file (default: <out-json stem>.url-samples.json)")
    p_collect.add_argument("--url-phase", default="sample1", choices=["sample1", "sample2", "skip"])
    p_collect.add_argument("--url-timeout", type=int, default=20)
    p_collect.set_defaults(func=cmd_collect)

    p_queue = sub.add_parser("queue", help="emit the usage-candidate review queue markdown")
    p_queue.add_argument("--methods-dir", default="data/methods")
    p_queue.add_argument("--out", required=True)
    p_queue.set_defaults(func=cmd_queue)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
