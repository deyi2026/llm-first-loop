#!/usr/bin/env python3
"""code_nav.py — 按需 Pyright 语义导航。

使用仓库已有的 pyright-langserver 做 Python 跨文件 references 与 callHierarchy，
每次调用起一个临时 LSP 子进程，查询完成后优雅 shutdown/exit；无常驻 daemon、
无持久索引、无每轮 tool schema 开销。

可信度契约：
  1) readiness：initialize -> initialized -> didOpen 后，必须收到目标文件的
     publishDiagnostics；未 ready 直接 fail-closed，不接受部分语义结果。
  2) semantic scope：LSP 结果只声明在当前 Pyright program/config scope 内成立。
  3) repo lexical complement：refs 默认对 git-visible Python 文件做独立文本交叉检查，
     lexical candidates 只用于提示复核，不能叫成 semantic missing references。

其它硬约束：
  - 所有 repo 内路径以 resolved repo root 为基准；目标必须位于 repo 内且为 .py。
  - symbol / prepareCallHierarchy 多候选时 fail-closed，不自动取第一个。
  - callers/callees 分离 site path 与 definition/target path，并保留全部 fromRanges。
  - server 提前退出、reader/framing/JSON 错误 fail-fast；未知 server request 回 -32601。
  - 同一 repo 使用 advisory lock 限制并发 langserver fan-out。
  - managed worktree 可从 Git common root 的共享 .venv 找 pyright-langserver。

用法：
  code_nav.py doctor                    # 自检：server/version/config/readiness
  code_nav.py refs <file> <symbol>      # semantic refs + lexical complement
  code_nav.py callers <file> <symbol>   # incoming callHierarchy
  code_nav.py callees <file> <symbol>   # outgoing callHierarchy

退出码：
  0 = 查询成功且有 semantic result；
  1 = 参数/环境/协议/readiness/ambiguity/lock/cross-check 等失败；
  2 = readiness 已确认、查询完成，但当前 semantic scope 内结果为 0。

机器输出使用 schema=lfl.code_nav.v1；先读 status/trust/scope，再读具体结果。
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from queue import Empty, Queue
from typing import Any
from urllib.parse import quote, unquote, urlparse

DEFAULT_TIMEOUT = 180.0
DEFAULT_READY_TIMEOUT = 60.0
DEFAULT_LOCK_TIMEOUT = 5.0


# ---------------------------------------------------------------- helpers
def path_to_uri(path: str) -> str:
    return "file://" + quote(os.path.abspath(path))


def uri_to_path(uri: str) -> str:
    p = urlparse(uri)
    return unquote(p.path) if p.scheme == "file" else uri


def find_root(start: str) -> str:
    """解析工作区根：优先 `start` 所在的 git 仓库，否则退回本脚本所在的仓库。

    只靠 cwd 的话，从仓库外调用会解析到非仓库目录，pyright 便找不到
    pyproject.toml → program 范围错乱（结果静默失准）。
    """
    script_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in (start, script_repo):
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=candidate,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            continue
    return os.path.abspath(start)


def resolve_target_path(root: str, raw: str) -> str:
    root_real = os.path.realpath(root)
    candidate = raw if os.path.isabs(raw) else os.path.join(root_real, raw)
    path = os.path.realpath(candidate)
    try:
        inside = os.path.commonpath([root_real, path]) == root_real
    except ValueError:
        inside = False
    if not inside:
        raise RuntimeError(f"目标文件必须位于 repo root 内: {raw}")
    if not os.path.isfile(path):
        raise RuntimeError(f"目标文件不存在或不是普通文件: {raw}")
    if not path.endswith(".py"):
        raise RuntimeError(f"code-nav v1 仅支持 Python 文件: {raw}")
    return path


class RepoLock:
    def __init__(self, root: str, timeout: float = DEFAULT_LOCK_TIMEOUT) -> None:
        key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:20]
        self.path = os.path.join(tempfile.gettempdir(), f"lfl-code-nav-{key}.lock")
        self.timeout = max(0.0, timeout)
        self._fp = None

    def __enter__(self) -> RepoLock:
        self._fp = open(self.path, "a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError as e:
                if time.monotonic() >= deadline:
                    self._fp.close()
                    self._fp = None
                    raise RuntimeError(
                        f"code-nav busy: repo lock 已被占用（timeout={self.timeout:.2f}s）"
                    ) from e
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self._fp is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
            self._fp.close()
            self._fp = None


def find_langserver(root: str) -> str | None:
    cand = os.path.join(root, ".venv", "bin", "pyright-langserver")
    if os.path.exists(cand):
        return cand
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if common.returncode == 0 and common.stdout.strip():
            common_dir = os.path.realpath(common.stdout.strip())
            common_root = (
                os.path.dirname(common_dir)
                if os.path.basename(common_dir) == ".git"
                else os.path.dirname(common_dir)
            )
            shared = os.path.join(common_root, ".venv", "bin", "pyright-langserver")
            if os.path.exists(shared):
                return shared
    except Exception:
        # pyright 探测失败回退下一个候选，导航不因探测失败中断
        pass
    from shutil import which

    return which("pyright-langserver")


def langserver_metadata(root: str, path: str | None) -> dict[str, str | None]:
    if not path:
        return {"source": None, "pyright_version": None}

    path_real = os.path.realpath(path)
    root_candidate = os.path.realpath(os.path.join(root, ".venv", "bin", "pyright-langserver"))
    source = "code_root_venv" if path_real == root_candidate else "PATH"

    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if common.returncode == 0 and common.stdout.strip():
            common_root = os.path.dirname(os.path.realpath(common.stdout.strip()))
            shared = os.path.realpath(
                os.path.join(common_root, ".venv", "bin", "pyright-langserver")
            )
            if path_real == shared:
                source = "git_common_root_venv"
    except Exception:
        # 来源标注是诊断附加值：git 探测失败时按未知来源继续
        pass

    version = None
    pyright = os.path.join(os.path.dirname(path_real), "pyright")
    if os.path.exists(pyright):
        try:
            proc = subprocess.run(
                [pyright, "--version"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                raw_version = proc.stdout.strip() or proc.stderr.strip()
                version = raw_version.splitlines()[0] if raw_version else None
        except Exception:
            # 版本槽位为观测附加值：探测失败保持 None，不影响定位主路径
            pass

    return {"source": source, "pyright_version": version}


def program_scope(root: str) -> dict[str, Any]:
    """如实回报 pyright 会分析哪些文件——这决定了 references 的完整性边界。"""
    info: dict[str, Any] = {"config_file": None, "include": None, "exclude": None, "note": ""}
    pj = os.path.join(root, "pyrightconfig.json")
    cfg_toml = os.path.join(root, "pyproject.toml")
    if os.path.exists(pj):
        try:
            with open(pj, encoding="utf-8") as f:
                d = json.load(f)
            info.update(
                config_file="pyrightconfig.json", include=d.get("include"), exclude=d.get("exclude")
            )
        except Exception as e:
            info["note"] = f"pyrightconfig.json 解析失败: {e}"
        return info
    if os.path.exists(cfg_toml):
        try:
            import tomllib

            with open(cfg_toml, "rb") as f:
                d = tomllib.load(f)
            pr = d.get("tool", {}).get("pyright")
            if pr:
                info.update(
                    config_file="pyproject.toml [tool.pyright]",
                    include=pr.get("include"),
                    exclude=pr.get("exclude"),
                )
            else:
                info["note"] = "pyproject.toml 无 [tool.pyright]，使用 pyright 默认范围"
        except Exception as e:
            info["note"] = f"pyproject.toml 解析失败: {e}"
    else:
        info["note"] = "未找到 pyrightconfig.json / pyproject.toml，使用默认范围"
    return info


DEF_PATTERNS = [
    r"\b(?:async\s+)?def\s+{n}\b",
    r"\bclass\s+{n}\b",
    r"\b{n}\s*[:=](?!=)",
    r"\b{n}\b",
]


def locate_symbol(path: str, symbol: str) -> tuple[int, int, str]:
    """返回 (line, char, 命中形态)。优先定义形态，避免落到调用点。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    esc = re.escape(symbol)
    for kind, pat in zip(("def", "class", "assign", "any"), DEF_PATTERNS, strict=True):
        rx = re.compile(pat.format(n=esc))
        matches: list[tuple[int, re.Match[str]]] = []
        for i, line in enumerate(lines):
            m = rx.search(line)
            if m:
                matches.append((i, m))
        if len(matches) > 1:
            rows = ", ".join(str(i + 1) for i, _ in matches[:20])
            suffix = "" if len(matches) <= 20 else f" ... 共 {len(matches)} 个"
            raise RuntimeError(
                f"符号 {symbol!r} 在 {path} 中存在多个 {kind} 候选（行 {rows}{suffix}）；"
                "请用显式行号消除歧义"
            )
        if matches:
            i, m = matches[0]
            # 定位到符号本身，而不是 `def `/`class ` 前缀
            off = m.group(0).find(symbol)
            return i, m.start() + max(off, 0), kind
    raise SystemExit(f"[code_nav] 在 {path} 中找不到符号 {symbol!r}")


# ---------------------------------------------------------------- LSP client
class LspClient:
    def __init__(self, cmd: list[str], root: str) -> None:
        self.root = root
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root
        )
        self._q: Queue[dict] = Queue()
        self._responses: dict[int, Any] = {}
        self._notifications: list[dict] = []
        self._id = 0
        self._t0 = time.monotonic()
        self.stderr_lines: list[str] = []
        self.server_logs: list[str] = []
        self.reader_error: str | None = None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    # -- io
    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            s = raw.decode("utf-8", "replace").rstrip()
            if s:
                self.stderr_lines.append(s)

    def _read_stdout(self) -> None:
        fp = self.proc.stdout
        assert fp is not None
        try:
            while True:
                headers: dict[str, str] = {}
                while True:
                    line = fp.readline()
                    if not line:
                        return
                    line = line.decode("utf-8", "replace").strip()
                    if not line:
                        break
                    if ":" in line:
                        k, _, v = line.partition(":")
                        headers[k.strip().lower()] = v.strip()
                n = int(headers.get("content-length", "0"))
                if n <= 0:
                    raise RuntimeError(f"invalid Content-Length: {n}")
                body = fp.read(n)
                if len(body) != n:
                    raise RuntimeError(f"short LSP frame: expected={n} actual={len(body)}")
                self._q.put(json.loads(body.decode("utf-8", "replace")))
        except Exception as e:
            self.reader_error = f"{type(e).__name__}: {e}"
            return

    def _check_health(self) -> None:
        if self.reader_error:
            raise RuntimeError(f"LSP reader protocol 解析失败: {self.reader_error}")
        rc = self.proc.poll()
        if rc is not None:
            tail = " | ".join(self.stderr_lines[-5:])
            detail = f"; stderr={tail}" if tail else ""
            raise RuntimeError(f"LSP server 已退出 returncode={rc}{detail}")

    def _send(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
            self.proc.stdin.flush()
        except OSError as e:
            rc = self.proc.poll()
            raise RuntimeError(f"LSP send 失败；server exit/returncode={rc}: {e}") from e

    def _serve_server_request(self, msg: dict) -> None:
        """server→client 请求必须应答，否则服务器会阻塞（漏答即为静默挂死）。"""
        method = msg["method"]
        params = msg.get("params") or {}
        if method == "window/workDoneProgress/create":
            result: Any = None
        elif method == "workspace/configuration":
            result = [{} for _ in params.get("items", [])]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": path_to_uri(self.root), "name": os.path.basename(self.root)}]
        elif method == "client/registerCapability":
            result = None
        else:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )
            return
        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def _pump(self, timeout: float) -> None:
        try:
            msg = self._q.get(timeout=timeout)
        except Empty:
            return
        if "method" in msg:
            if "id" in msg:
                self._serve_server_request(msg)
            else:
                m = msg["method"]
                if m == "window/logMessage":
                    self.server_logs.append(str((msg.get("params") or {}).get("message", "")))
                else:
                    self._notifications.append(msg)
        else:
            self._responses[msg.get("id")] = msg

    def request(self, method: str, params: dict, timeout: float) -> Any:
        self._check_health()
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while rid not in self._responses:
            self._check_health()
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{method} 在 {timeout:.0f}s 内未返回（服务器可能仍在分析）")
            self._pump(min(0.25, left))
        msg = self._responses.pop(rid)
        if "error" in msg:
            raise RuntimeError(f"{method} 失败: {msg['error']}")
        return msg.get("result")

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def wait_notification(self, predicate, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            for i, n in enumerate(self._notifications):
                if predicate(n):
                    return self._notifications.pop(i)
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self._check_health()
            self._pump(min(0.25, left))

    # -- protocol
    def initialize(self) -> dict:
        """返回 server capabilities（注意：不是 InitializeResult 本身）。"""
        result = self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": path_to_uri(self.root),
                "workspaceFolders": [
                    {"uri": path_to_uri(self.root), "name": os.path.basename(self.root)}
                ],
                "capabilities": {
                    "window": {"workDoneProgress": True},
                    "workspace": {"workspaceFolders": True, "symbol": {}, "configuration": True},
                    "textDocument": {
                        "references": {},
                        "definition": {},
                        "callHierarchy": {},
                        "documentSymbol": {},
                        "publishDiagnostics": {},
                    },
                },
            },
            timeout=60.0,
        )
        # initialized 是必需通知：缺它则后续请求永不返回（实测连 3 文件 fixture 也不回）
        self.notify("initialized", {})
        return (result or {}).get("capabilities") or {}

    def open_file(self, path: str) -> None:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path_to_uri(path),
                    "languageId": "python",
                    "version": 1,
                    "text": text,
                }
            },
        )

    def await_analysis(self, path: str, timeout: float) -> bool:
        """就绪门：等到该文件的 publishDiagnostics 才认为已被分析。"""
        target = path_to_uri(path)
        n = self.wait_notification(
            lambda m: (
                m["method"] == "textDocument/publishDiagnostics"
                and (m.get("params") or {}).get("uri") == target
            ),
            timeout,
        )
        return n is not None

    def close(self) -> None:
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.request("shutdown", {}, timeout=2.0)
            with contextlib.suppress(Exception):
                self.notify("exit", {})
            with contextlib.suppress(Exception):
                self.proc.wait(timeout=2.0)
        with contextlib.suppress(Exception):
            if self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
        with contextlib.suppress(Exception):
            if self.proc.poll() is None:
                self.proc.kill()


def new_client(root: str) -> LspClient:
    ls = find_langserver(root)
    if not ls:
        raise SystemExit(
            "[code_nav] 找不到 pyright-langserver；请确认 .venv 已装 pyright（pyproject dev 依赖）"
        )
    return LspClient([ls, "--stdio"], root)


def _repo_relative(path: str, root: str) -> str:
    path_real = os.path.realpath(path)
    root_real = os.path.realpath(root)
    try:
        if os.path.commonpath([path_real, root_real]) == root_real:
            return os.path.relpath(path_real, root_real)
    except ValueError:
        pass
    return path_real


def ref_to_row(loc: dict, root: str) -> dict:
    rng = loc.get("range") or (loc.get("targetRange") or {})
    start = rng.get("start", {})
    p = uri_to_path(loc.get("uri") or (loc.get("targetUri") or ""))
    rel = _repo_relative(p, root)
    return {"path": rel, "line": start.get("line", 0) + 1, "col": start.get("character", 0) + 1}


# ---------------------------------------------------------------- commands
def cmd_doctor(args: argparse.Namespace) -> int:
    root = args.root or find_root(os.getcwd())
    scope = program_scope(root)
    ls = find_langserver(root)
    meta = langserver_metadata(root, ls)
    report: dict[str, Any] = {
        "root": root,
        "langserver": ls,
        "langserver_source": meta["source"],
        "pyright_version": meta["pyright_version"],
        "scope": scope,
    }
    if not ls:
        report["ok"] = False
        report["error"] = "pyright-langserver 不存在"
        _emit(report, args, ["[code_nav] doctor: 失败 — 未找到 pyright-langserver"])
        return 1
    t0 = time.monotonic()
    c = new_client(root)
    try:
        caps = c.initialize()
        report["capabilities"] = {
            "references": bool(caps.get("referencesProvider")),
            "callHierarchy": bool(caps.get("callHierarchyProvider")),
            "definition": bool(caps.get("definitionProvider")),
        }
        report["cold_start_s"] = round(time.monotonic() - t0, 2)
        # canary：documentSymbol 不需要 program，只验证请求-响应通路 + 就绪门。
        # 优先选 program 范围内的文件，否则就绪门信号不代表真实查询路径。
        target = ""
        for cand in ("src/llm_loop/core/message.py", "scripts/code_nav.py"):
            if os.path.exists(os.path.join(root, cand)):
                target = os.path.join(root, cand)
                break
        report["canary_file"] = os.path.relpath(target, root) if target else None
        if target:
            c.open_file(target)
            ready = c.await_analysis(target, args.ready_timeout)
            report["readiness_gate_confirmed"] = ready
            if not ready:
                report["ok"] = False
                report["status"] = "not_ready"
                report["error"] = "未收到目标文件 publishDiagnostics；拒绝接受未完成分析结果"
                _emit(
                    report,
                    args,
                    [
                        "[code_nav] doctor: NOT_READY — 未收到目标文件 publishDiagnostics；"
                        "未执行 canary semantic query"
                    ],
                )
                return 1
            t1 = time.monotonic()
            syms = c.request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": path_to_uri(target)}},
                timeout=args.timeout,
            )
            report["canary_symbols"] = len(syms or [])
            report["canary_latency_s"] = round(time.monotonic() - t1, 2)
        report["ok"] = True
        report["status"] = "ok"
    finally:
        c.close()
    lines = [
        f"root            : {report['root']}",
        f"langserver      : {report['langserver']}",
        f"langserver src  : {report.get('langserver_source')}",
        f"pyright version : {report.get('pyright_version')}",
        f"program scope   : {scope.get('config_file')} include={scope.get('include')} exclude={scope.get('exclude')}",
        f"note            : {scope.get('note') or '-'}",
        f"capabilities    : {report.get('capabilities')}",
        f"cold start      : {report.get('cold_start_s')}s",
        f"readiness gate  : {report.get('readiness_gate_confirmed')}",
        f"canary          : {report.get('canary_symbols')} symbols in {report.get('canary_latency_s')}s",
    ]
    _emit(report, args, lines)
    return 0


SKIP_DIRS = {
    ".git",
    ".venv",
    ".worktrees",
    ".backup",
    ".tmp-ci",
    ".opencode",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "data",
    "dist",
    "build",
}


def cross_check(
    symbol: str,
    root: str,
    known: set[str],
    scope: dict[str, Any] | None = None,
) -> dict:
    """扫描 repo-visible Python 文件中的 lexical candidates。

    universe 由 git tracked + non-ignored untracked Python 文件组成。这里的命中只
    是词法候选，不能升级为“Pyright 漏掉的 semantic reference”。
    """
    rx = re.compile(r"\b" + re.escape(symbol) + r"\b")
    by_dir: dict[str, int] = {}
    matching_files = 0
    matching_lines = 0
    occurrences = 0
    includes = (scope or {}).get("include")
    simple_includes = (
        [os.path.normpath(str(x)).rstrip(os.sep) for x in includes]
        if isinstance(includes, list) and all(not re.search(r"[*?\[\]]", str(x)) for x in includes)
        else None
    )
    inside_files = 0
    inside_occurrences = 0
    outside_files = 0
    outside_occurrences = 0
    proc = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "--", "*.py"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git-visible lexical cross-check 失败: {proc.stderr.strip()}")
    known_norm = {os.path.normpath(p) for p in known}
    for rel_raw in proc.stdout.splitlines():
        rel = os.path.normpath(rel_raw)
        if not rel or rel in known_norm:
            continue
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="ignore") as fh:
                lines = fh.read().splitlines()
        except Exception:
            continue
        line_hits = [len(rx.findall(line)) for line in lines]
        n = sum(line_hits)
        if n:
            matching_files += 1
            matching_lines += sum(1 for count in line_hits if count)
            occurrences += n
            top = rel.split(os.sep)[0]
            by_dir[top] = by_dir.get(top, 0) + n
            if simple_includes is not None:
                inside = any(rel == inc or rel.startswith(inc + os.sep) for inc in simple_includes)
                if inside:
                    inside_files += 1
                    inside_occurrences += n
                else:
                    outside_files += 1
                    outside_occurrences += n
    return {
        "universe": "git-visible-python",
        "lsp_result_files": len(known_norm),
        "lexical_only_files": matching_files,
        "matching_files": matching_files,
        "matching_lines": matching_lines,
        "occurrences": occurrences,
        "by_top_level_dir": dict(sorted(by_dir.items(), key=lambda kv: (-kv[1], kv[0]))),
        "include_classifier": (
            "exact-prefix"
            if simple_includes is not None
            else ("unknown" if includes is None else "unsupported")
        ),
        "inside_configured_include": {
            "matching_files": inside_files,
            "occurrences": inside_occurrences,
        },
        "outside_configured_include": {
            "matching_files": outside_files,
            "occurrences": outside_occurrences,
        },
    }


def cmd_refs(args: argparse.Namespace) -> int:
    root = args.root or find_root(os.getcwd())
    path = resolve_target_path(root, args.file)
    line, ch, kind = locate_symbol(path, args.symbol)
    scope = program_scope(root)
    t0 = time.monotonic()
    c = new_client(root)
    try:
        c.initialize()
        c.open_file(path)
        ready = c.await_analysis(path, args.ready_timeout)
        if not ready:
            payload = {
                "schema": "lfl.code_nav.v1",
                "operation": "refs",
                "status": "not_ready",
                "symbol": args.symbol,
                "file": args.file,
                "resolved_as": kind,
                "trust": {
                    "analysis_ready": False,
                    "readiness_signal": "textDocument/publishDiagnostics",
                },
                "scope": scope,
                "caveats": [
                    "就绪门未确认；拒绝执行 references，以避免把未完成分析结果当成完整语义结果"
                ],
                "refs": [],
            }
            _emit(
                payload,
                args,
                ["NOT_READY | no semantic result accepted | reason=publishDiagnostics timeout"],
            )
            return 1
        res = c.request(
            "textDocument/references",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line, "character": ch},
                "context": {"includeDeclaration": True},
            },
            timeout=args.timeout,
        )
        rows = [ref_to_row(x, root) for x in (res or [])]
    finally:
        c.close()
    elapsed = round(time.monotonic() - t0, 2)
    cc = (
        None
        if args.no_cross_check
        else cross_check(args.symbol, root, {r["path"] for r in rows}, scope)
    )
    caveats = _caveats(scope, ready, cc)
    payload = {
        "schema": "lfl.code_nav.v1",
        "operation": "refs",
        "status": "ok" if rows else "no_results",
        "symbol": args.symbol,
        "file": args.file,
        "resolved_as": kind,
        "count": len(rows),
        "files": len({r["path"] for r in rows}),
        "elapsed_s": elapsed,
        "readiness_gate_confirmed": ready,
        "trust": {
            "analysis_ready": True,
            "readiness_signal": "textDocument/publishDiagnostics",
            "semantic_scope": scope,
            "repo_lexical_cross_check": "not_checked" if cc is None else "complete",
        },
        "scope": scope,
        "cross_check": cc,
        "caveats": caveats,
        "refs": rows,
    }
    lines = [
        f"{len(rows)} 引用 / {payload['files']} 文件  ({elapsed}s, ready={ready}, 命中形态={kind})"
    ]
    lines += [f"  {r['path']}:{r['line']}:{r['col']}" for r in rows[: args.limit]]
    if len(rows) > args.limit:
        lines.append(f"  ... 另有 {len(rows) - args.limit} 条")
    lines += [f"  [!] {c}" for c in caveats]
    _emit(payload, args, lines)
    return 0 if rows else 2


def _hierarchy(args: argparse.Namespace, direction: str) -> int:
    root = args.root or find_root(os.getcwd())
    path = resolve_target_path(root, args.file)
    line, ch, kind = locate_symbol(path, args.symbol)
    scope = program_scope(root)
    t0 = time.monotonic()
    c = new_client(root)
    try:
        c.initialize()
        c.open_file(path)
        ready = c.await_analysis(path, args.ready_timeout)
        if not ready:
            payload = {
                "schema": "lfl.code_nav.v1",
                "operation": direction,
                "status": "not_ready",
                "symbol": args.symbol,
                "file": args.file,
                "resolved_as": kind,
                "trust": {
                    "analysis_ready": False,
                    "readiness_signal": "textDocument/publishDiagnostics",
                },
                "scope": scope,
                "caveats": [
                    "就绪门未确认；拒绝执行 callHierarchy，以避免把未完成分析结果当成完整语义结果"
                ],
                "calls": [],
            }
            _emit(
                payload,
                args,
                ["NOT_READY | no semantic result accepted | reason=publishDiagnostics timeout"],
            )
            return 1
        items = c.request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": path_to_uri(path)},
                "position": {"line": line, "character": ch},
            },
            timeout=args.timeout,
        )
        if items and len(items) > 1:
            names = ", ".join(
                f"{item.get('name', '?')}@"
                f"{(item.get('selectionRange') or {}).get('start', {}).get('line', 0) + 1}"
                for item in items[:20]
            )
            raise RuntimeError(
                f"prepareCallHierarchy 返回多个候选（{len(items)}）: {names}；拒绝自动选择第一个"
            )
        if not items:
            rows: list[dict] = []
        else:
            method = (
                "callHierarchy/incomingCalls"
                if direction == "callers"
                else "callHierarchy/outgoingCalls"
            )
            calls = c.request(method, {"item": items[0]}, timeout=args.timeout)
            rows = []
            for entry in calls or []:
                ranges = entry.get("fromRanges") or []
                site_lines = [r.get("start", {}).get("line", 0) + 1 for r in ranges]
                if direction == "callers":
                    caller = entry.get("from") or {}
                    loc = caller.get("selectionRange") or caller.get("range") or {}
                    start = loc.get("start", {})
                    caller_path = _repo_relative(uri_to_path(caller.get("uri", "")), root)
                    rows.append(
                        {
                            "name": caller.get("name", ""),
                            "site_path": caller_path,
                            "site_lines": site_lines,
                            "caller_definition_path": caller_path,
                            "caller_definition_line": start.get("line", 0) + 1,
                            "caller_definition_col": start.get("character", 0) + 1,
                        }
                    )
                else:
                    target = entry.get("to") or {}
                    loc = target.get("selectionRange") or target.get("range") or {}
                    start = loc.get("start", {})
                    rows.append(
                        {
                            "name": target.get("name", ""),
                            "site_path": _repo_relative(path, root),
                            "site_lines": site_lines,
                            "target_path": _repo_relative(uri_to_path(target.get("uri", "")), root),
                            "target_definition_line": start.get("line", 0) + 1,
                            "target_definition_col": start.get("character", 0) + 1,
                        }
                    )
    finally:
        c.close()
    elapsed = round(time.monotonic() - t0, 2)
    caveats = _caveats(scope, ready) + [
        "site_lines 是调用点；definition_line 是函数定义位置（selectionRange）。"
        "两者路径语义分离，且保留全部 fromRanges。"
    ]
    payload = {
        "schema": "lfl.code_nav.v1",
        "operation": direction,
        "status": "ok" if rows else "no_results",
        "symbol": args.symbol,
        "direction": direction,
        "count": len(rows),
        "elapsed_s": elapsed,
        "readiness_gate_confirmed": ready,
        "trust": {
            "analysis_ready": True,
            "readiness_signal": "textDocument/publishDiagnostics",
            "semantic_scope": scope,
        },
        "scope": scope,
        "caveats": caveats,
        "calls": rows,
    }
    lines = [
        f"{len(rows)} 个{'调用者' if direction == 'callers' else '被调用'}  ({elapsed}s, ready={ready})"
    ]
    if direction == "callers":
        lines += [
            (
                f"  {r['site_path']}:{','.join(str(x) for x in r['site_lines'])}"
                f"  ← {r['name']}() 定义在 "
                f"{r['caller_definition_path']}:{r['caller_definition_line']}"
            )
            for r in rows[: args.limit]
        ]
    else:
        lines += [
            (
                f"  {r['site_path']}:{','.join(str(x) for x in r['site_lines'])}"
                f"  → {r['target_path']}:{r['target_definition_line']} {r['name']}()"
            )
            for r in rows[: args.limit]
        ]
    lines += [f"  [!] {c}" for c in caveats]
    _emit(payload, args, lines)
    return 0 if rows else 2


def _caveats(scope: dict, ready: bool | None, cc: dict | None = None) -> list[str]:
    out: list[str] = []
    if ready is False:
        out.append(
            "就绪门未确认（未收到该文件的 publishDiagnostics）——结果可能是分析未完成时的静默假阴性"
        )
    inc = scope.get("include")
    if cc is None:
        out.append(
            f"references 只在 program 范围 include={inc} 内查找；范围外命中**未检查**"
            if inc
            else "未解析到 include，program 范围不确定——完整性无法保证"
        )
        return out
    if cc["matching_files"]:
        out.append(
            f"repo-visible lexical complement 另有 {cc['occurrences']} 次 / "
            f"{cc['matching_lines']} 行 / {cc['matching_files']} 个文件命中，"
            f"分布 {cc['by_top_level_dir']}。这些是 lexical candidates，"
            "不能直接解释为 Pyright 漏掉的 semantic references。"
        )
    else:
        out.append("repo-visible lexical complement 未发现额外文本候选")
    if not inc:
        out.append("未解析到 include，program 范围不确定——完整性无法保证")
    return out


def _emit(payload: dict, args: argparse.Namespace, lines: list[str]) -> None:
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))


def _add_common(p: argparse.ArgumentParser, suppress: bool) -> None:
    """让选项在子命令前/后都可用。

    子命令侧的副本必须用 SUPPRESS 作默认值：argparse 的子解析器会把自身默认值
    回写到 namespace，非 SUPPRESS 的默认值会覆盖掉顶层已解析出的 --json 等值。
    """
    kw: dict[str, Any] = {"default": argparse.SUPPRESS} if suppress else {}

    def d(fallback: Any) -> Any:
        return kw.get("default", fallback)

    p.add_argument("--root", help="工作区根（默认 git toplevel）", **kw)
    p.add_argument("--json", action="store_true", help="输出 JSON", **kw)
    p.add_argument("--timeout", type=float, default=d(DEFAULT_TIMEOUT), help="单请求超时秒")
    p.add_argument(
        "--ready-timeout", type=float, default=d(DEFAULT_READY_TIMEOUT), help="就绪门等待秒"
    )
    p.add_argument("--limit", type=int, default=d(40), help="文本输出条数上限")
    p.add_argument(
        "--lock-timeout",
        type=float,
        default=d(DEFAULT_LOCK_TIMEOUT),
        help="同一 repo code-nav 并发锁等待秒",
    )
    p.add_argument(
        "--no-cross-check",
        action="store_true",
        help="跳过 program 范围外交叉检查（省几秒，但会掩盖静默缺失）",
        **kw,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="code_nav.py", description="零常驻代码导航（LSP 按需驱动）")
    _add_common(ap, suppress=False)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def newsub(name: str, helptext: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=helptext)
        _add_common(p, suppress=True)
        return p

    newsub("doctor", "自检服务器/配置/就绪门").set_defaults(func=cmd_doctor)
    p = newsub("refs", "引用点")
    p.add_argument("file")
    p.add_argument("symbol")
    p.set_defaults(func=cmd_refs)
    for name, direction in (("callers", "callers"), ("callees", "callees")):
        p = newsub(name, "调用者/被调用者")
        p.add_argument("file")
        p.add_argument("symbol")
        p.set_defaults(func=lambda a, d=direction: _hierarchy(a, d))
    args = ap.parse_args(argv)
    try:
        args.root = os.path.realpath(args.root or find_root(os.getcwd()))
        with RepoLock(args.root, timeout=args.lock_timeout):
            return args.func(args)
    except TimeoutError as e:
        print(f"[code_nav] 超时：{e}", file=sys.stderr)
        return 1
    except (RuntimeError, SystemExit) as e:
        print(f"[code_nav] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
