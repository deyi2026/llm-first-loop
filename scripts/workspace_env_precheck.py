#!/usr/bin/env python3
"""停机前 .env 结构预检（P1-3 编排恢复路径修复，2026-10-25）.

背景（生产事故 orchestration-20261025-163049）：
  .env 在 2026-10-25 07:52 被 auth.py rehash 写回 bug 污染——
  WEB_LOGIN_PASSWORD_HASH 行尾缺换行导致 WEB_SESSION_TTL_SECONDS 拼入哈希行。
  停机重启后服务重读 .env，登录配置无效 → /auth/status 300s 未就绪 →
  编排在 health 步失败退出（无回滚、锁残留）。auth.py 本体已修复
  （commit 16a90f7a0）；本模块是编排层的独立防线：停服前结构校验，
  坏配置直接中止于停服前（服务未动），把事故拦截在停机窗口之前。

校验内容（结构层，不打印任何值）：
  1. 原始行扫描：WEB_LOGIN_PASSWORD_HASH 行独立完整——正则单行匹配
     ^WEB_LOGIN_PASSWORD_HASH=pbkdf2_sha256$N$salt$digest（auth._b64encode=
     urlsafe b64 去 padding；字符类 [A-Za-z0-9+/=_-] 兼容历史标准字母表），
     不允许与其它字段拼接；关键键（哈希/TTL）出现多条赋值行=歧义=失败；
     关键键名出现在其它行的行内（非独立行首）=疑似拼接污染=失败。
  2. 独立重读解析（模拟重启重读）：用与服务链相同的解析器
     llm_loop.runtime.resolver.parse_env_file 重新解析整个 .env，对解析值
     直接调用 auth.py 权威校验器 _parse_password_hash（判据零漂移；仅当
     auth 不可导入时退回本文件镜像判据）；重读值必须与独立行原值一致。
     WEB_SESSION_TTL_SECONDS：纯整数秒，1<=ttl<=604800（auth 上限 7 天）。
  3. 输出 JSON {"ok", "issues", "notes", "env_file", "ts"}——issues 只含
     键名/行号/原因，绝不含值（哈希盐/摘要/密钥）。

退出码：0=通过；2=校验失败（编排据此在停服前中止）。

用法：python scripts/workspace_env_precheck.py /path/to/.env [--strict-missing-hash]
  --strict-missing-hash：WEB_LOGIN_PASSWORD_HASH 整体缺失也判失败
  （生产启用登录时使用；默认缺失仅提示不阻断）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_loop.runtime.resolver import parse_env_file  # noqa: E402

# 与 src/llm_loop/web/auth.py 判据镜像（auth 不可导入时的退路；正常路径直接
# 复用 auth._parse_password_hash 权威校验器，判据零漂移）。
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_MIN_ITERATIONS = 100_000
_PASSWORD_MAX_ITERATIONS = 2_000_000
_MAX_SESSION_TTL_S = 7 * 24 * 60 * 60

try:  # 权威校验器（auth.py 已由 commit 16a90f7a0 修复；本模块只读复用不改它）
    from llm_loop.web.auth import _parse_password_hash as _auth_parse_hash
except Exception:  # noqa: BLE001 — 依赖缺失时退回镜像判据，不静默放行
    _auth_parse_hash = None

CRITICAL_KEYS = ("WEB_LOGIN_PASSWORD_HASH", "WEB_SESSION_TTL_SECONDS")

# 独立完整哈希行：键=行首、值=pbkdf2_sha256$N$salt$digest、行尾仅允许空白/注释。
# b64 段字符类含 urlsafe 的 -_ 与历史标准字母表 +/=（类内均无需转义）；
# 实测生产 .env 哈希 salt=22 字符/16 字节、digest=43 字符/32 字节（无 padding）。
_HASH_LINE_RE = re.compile(
    r"^WEB_LOGIN_PASSWORD_HASH=pbkdf2_sha256\$\d{1,9}\$[A-Za-z0-9+/=_-]+\$[A-Za-z0-9+/=_-]+\s*(?:#.*)?$"
)
_HASH_VALUE_RE = re.compile(
    r"^pbkdf2_sha256\$\d{1,9}\$[A-Za-z0-9+/=_-]+\$[A-Za-z0-9+/=_-]+$"
)
_TTL_LINE_RE = re.compile(r"^WEB_SESSION_TTL_SECONDS=\d+\s*(?:#.*)?$")

# b64 段内 '=' 只允许作末尾 padding（0-2 个）——行级拼接检测：
# “哈希值WEB_SESSION_TTL_SECONDS=43200” 这类拼接会把 '=' 带进段中部。
_B64_SEG_RE = re.compile(r"[A-Za-z0-9+/_-]*={0,2}")


def _hash_body_has_glue(body: str) -> str | None:
    """返回行内拼接证据描述（无拼接返回 None）；body=哈希行 '=' 之后的值体."""
    parts = body.split("$")
    if len(parts) == 4:
        for seg_name, seg in (("salt", parts[2]), ("digest", parts[3])):
            if not _B64_SEG_RE.fullmatch(seg):
                return f"{seg_name} 段中部出现 '='（b64 padding 只允许在段尾）"
    for key in CRITICAL_KEYS:
        if f"{key}=" in body:
            return f"值体内嵌关键键名 {key}=（拼接特征）"
    return None


def _b64decode_len(value: str) -> int:
    """urlsafe b64 解码后字节数（镜像 auth._b64decode 的 padding 回补）."""
    return len(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))


def _parse_hash_value(value: str) -> tuple[int, int, int] | None:
    """值级校验；返回 (iterations, salt_len, digest_len)，失败 None.

    优先复用 auth._parse_password_hash（权威判据：iterations 范围/salt>=16B/
    digest==32B/urlsafe b64 可解码）。
    """
    if _auth_parse_hash is not None:
        try:
            iterations, salt, digest = _auth_parse_hash(value)
            return iterations, len(salt), len(digest)
        except ValueError:
            return None
    # 退路：镜像判据（与 auth 同判据；仅当 auth 模块不可导入时使用）
    m = _HASH_VALUE_RE.match(value)
    if not m:
        return None
    parts = value.split("$")
    iterations = int(parts[1])
    try:
        salt_len = _b64decode_len(parts[2])
        digest_len = _b64decode_len(parts[3])
    except (ValueError, TypeError):
        return None
    if not (_PASSWORD_MIN_ITERATIONS <= iterations <= _PASSWORD_MAX_ITERATIONS):
        return None
    if salt_len < 16 or digest_len != hashlib.sha256().digest_size:
        return None
    return iterations, salt_len, digest_len


def _hash_value_issue_reason(value: str) -> str:
    """值校验失败时的具体原因（不含值本身）."""
    if not _HASH_VALUE_RE.match(value):
        return "重读值不符合 pbkdf2_sha256$N$salt$digest 四段结构"
    parts = value.split("$")
    try:
        iterations = int(parts[1])
    except ValueError:
        return "iterations 非整数"
    if not (_PASSWORD_MIN_ITERATIONS <= iterations <= _PASSWORD_MAX_ITERATIONS):
        return (
            f"iterations 越界（安全范围 {_PASSWORD_MIN_ITERATIONS}-{_PASSWORD_MAX_ITERATIONS}）"
        )
    try:
        salt_len = _b64decode_len(parts[2])
        digest_len = _b64decode_len(parts[3])
    except (ValueError, TypeError):
        return "salt/digest 非法 base64"
    if salt_len < 16:
        return "salt 长度不足 16 字节"
    if digest_len != hashlib.sha256().digest_size:
        return "digest 长度非 32 字节（SHA-256）"
    return "未通过 auth 权威校验"


def check_env_structure(env_file: Path, *, strict_missing_hash: bool = False) -> dict:
    """结构校验主入口；返回报告 dict（ok/issues/notes，不含任何值）."""
    issues: list[str] = []
    notes: list[str] = []

    if not env_file.is_file():
        return {
            "ok": False,
            "env_file": str(env_file),
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "issues": [f".env 文件不存在: {env_file}（停服前必须存在且可解析）"],
            "notes": notes,
        }

    try:
        raw_lines = env_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "env_file": str(env_file),
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "issues": [f".env 不可读/非 UTF-8: {type(exc).__name__}（拒绝在停服前放行）"],
            "notes": notes,
        }

    # ── 1) 原始行扫描：关键键独立成行 ──
    hash_lines: list[int] = []
    ttl_lines: list[int] = []
    for idx, line in enumerate(raw_lines, start=1):
        if line.startswith("WEB_LOGIN_PASSWORD_HASH="):
            hash_lines.append(idx)
            if not _HASH_LINE_RE.match(line):
                issues.append(
                    f"WEB_LOGIN_PASSWORD_HASH 第 {idx} 行非独立完整的 "
                    "pbkdf2_sha256$N$salt$digest 单值（疑似行尾拼接/污染/格式损坏）"
                )
            else:
                glue = _hash_body_has_glue(line.split("=", 1)[1].split("#", 1)[0].strip())
                if glue:
                    issues.append(
                        f"WEB_LOGIN_PASSWORD_HASH 第 {idx} 行非独立单值: {glue}"
                    )
        elif line.startswith("WEB_SESSION_TTL_SECONDS="):
            ttl_lines.append(idx)
            if not _TTL_LINE_RE.match(line):
                issues.append(
                    f"WEB_SESSION_TTL_SECONDS 第 {idx} 行值非纯整数秒（结构异常）"
                )
        else:
            # 关键键名出现在其它行内（非行首独立赋值）→ 拼接污染特征。
            # 审核P2-3: 与 auth.py:286 对称，export KEY= 形式视为独立赋值行
            # （否则合法 export 形式会被误判"疑似拼入"而 fail-closed 误拒）。
            if any(re.fullmatch(rf"export\s+{re.escape(k)}=.*", line) for k in CRITICAL_KEYS):
                continue
            for key in CRITICAL_KEYS:
                if re.search(rf"{key}=", line):
                    issues.append(
                        f"{key} 出现在第 {idx} 行的非独立位置（疑似被拼入其它行；"
                        "常见于上一行行尾缺换行的写回 bug）"
                    )
    if len(hash_lines) > 1:
        issues.append(f"WEB_LOGIN_PASSWORD_HASH 出现 {len(hash_lines)} 个赋值行（歧义，拒绝）")
    if len(ttl_lines) > 1:
        issues.append(f"WEB_SESSION_TTL_SECONDS 出现 {len(ttl_lines)} 个赋值行（歧义，拒绝）")

    # ── 2) 独立重读解析（模拟重启重读；与服务链同一解析器）──
    try:
        parsed = parse_env_file(env_file)
    except Exception as exc:  # noqa: BLE001 — 解析器异常如实拦截
        issues.append(f"独立重读解析失败: {type(exc).__name__}（拒绝在停服前放行）")
        parsed = {}

    if parsed:
        raw_hash = next(
            (raw_lines[i - 1].split("=", 1)[1].split("#", 1)[0].strip()
             for i in hash_lines), ""
        ) if hash_lines else ""
        parsed_hash = parsed.get("WEB_LOGIN_PASSWORD_HASH", "")
        if hash_lines:
            if not parsed_hash:
                issues.append("WEB_LOGIN_PASSWORD_HASH 有独立行但重读解析不到值（解析器丢弃）")
            elif parsed_hash != raw_hash:
                issues.append(
                    "WEB_LOGIN_PASSWORD_HASH 重读值与独立行原值不一致（注释剥离/引号异常）"
                )
            if parsed_hash and _parse_hash_value(parsed_hash) is None:
                issues.append(
                    "WEB_LOGIN_PASSWORD_HASH 重读值未通过登录哈希校验: "
                    + _hash_value_issue_reason(parsed_hash)
                )
        elif strict_missing_hash:
            issues.append("WEB_LOGIN_PASSWORD_HASH 整体缺失（--strict-missing-hash 模式下判失败）")
        else:
            notes.append("WEB_LOGIN_PASSWORD_HASH 未配置（未启用密码登录时无影响；生产启用登录须配置）")

        parsed_ttl = parsed.get("WEB_SESSION_TTL_SECONDS", "")
        if parsed_ttl:
            if not parsed_ttl.isdigit() or not (1 <= int(parsed_ttl) <= _MAX_SESSION_TTL_S):
                issues.append(
                    "WEB_SESSION_TTL_SECONDS 重读值非有效整数秒（1-604800）"
                )
        elif ttl_lines:
            issues.append("WEB_SESSION_TTL_SECONDS 有独立行但重读解析不到值")
        else:
            notes.append("WEB_SESSION_TTL_SECONDS 未配置（重读后走默认 12h）")

    return {
        "ok": not issues,
        "env_file": str(env_file),
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "issues": issues,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="停机前 .env 结构预检（不打印值）")
    parser.add_argument("env_file", type=Path)
    parser.add_argument(
        "--strict-missing-hash", action="store_true",
        help="WEB_LOGIN_PASSWORD_HASH 整体缺失也判失败",
    )
    args = parser.parse_args(argv)
    report = check_env_structure(
        args.env_file, strict_missing_hash=args.strict_missing_hash
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
