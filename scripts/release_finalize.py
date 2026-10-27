#!/usr/bin/env python3
"""draft-first 发布语义：平台工件 manifest 生成 + 机械转正门禁（T3, 2026-10-27）。

目标语义（用户已批准）：
1. Release 一律以 draft 创建并长期保持为默认中间态；draft→published 只由本脚本
   的机械判据触发（finalize-release.yml workflow_dispatch），不再人工点 publish。
2. release-artifacts-manifest.json 作为 Release 资产上传，是平台状态与逐资产
   sha256 的权威记录；finalize 下载 Release 实际资产逐一实测 sha256 与 manifest
   比对，防止上传错包/替换包。
3. 转正判据（全部满足才允许 --draft=false）：
   a) 所有 required 平台（默认 linux_x86_64 / linux_aarch64 / macos_arm64）ready；
   b) manifest 每个资产的 sha256 与 size 和 Release 实际资产逐一相符；
   c) Release 上没有 manifest 未申报的多余资产；
   d) 正文状态块（HTML 注释包裹 fenced JSON）由本脚本维护；非全绿时正文不得
      出现 latest/最新可用性承诺（发现即作为违规上报，不代为修改正文）。
4. 任一判据不满足：保持 draft、输出缺项清单（哪个平台/缺什么/期望文件名）、
   非零退出、绝不删改已有 Release（失败路径只读）。
5. 幂等：对已 published 的 Release 重放 finalize 直接成功且零写操作；对仍
   draft 的重复 finalize 判定结果一致（无破坏性写）。

用法：
  # CI（release.yml，创建 draft 前一步）：从 dist/ 本地生成 manifest 与正文状态块
  python scripts/release_finalize.py manifest --from-dir dist --tag "$RELEASE_TAG" \
      --commit-sha "$GITHUB_SHA" --out dist/release-artifacts-manifest.json \
      --body-out dist/release-body-status.md

  # Release 创建后：把状态块幂等写入正文（置顶；已存在则原位替换）
  python scripts/release_finalize.py body --tag "$RELEASE_TAG" \
      --repo "$GITHUB_REPOSITORY" --block-file dist/release-body-status.md

  # macOS 签名机（本机签名后上传 .pkg 之时）：
  gh release upload v0.6.38 LFL-0.6.38-macos-arm64*.pkg --clobber
  python scripts/release_finalize.py manifest --tag v0.6.38 --repo <owner/repo>
  #   （按 Release 实际资产重生成 manifest 并回传；已 published 的 Release 拒绝改写）

  # 转正（等价于原“人工点 publish”）：
  python scripts/release_finalize.py finalize --tag v0.6.38 --repo <owner/repo>
  #   通常经 finalize-release.yml workflow_dispatch(tag) 触发，与 release.yml 共用
  #   release-refs/tags/<tag> 串行组（single-writer 不变，绝不 cancel-in-progress）。

  # 离线自检（无网络、无 gh）：
  python scripts/release_finalize.py --self-check

平台资格规则：
  - 文件名含 macos/darwin 或 *.pkg/*.dmg → 工件平台 macos_arm64；
  - 文件名含 linux（install_linux.sh/uninstall_linux.sh 等）→ 工件平台 linux
    （同时覆盖 linux_x86_64 与 linux_aarch64 两个发布平台）；
  - 其余（纯 Python wheel/sdist、报告）→ any（同样覆盖两个 Linux 发布平台）；
  - 辅助工件（*.sha256、*-smoke.json、SHA256SUMS）required=false，不参与
    ready 判定——防止「只上传 .pkg.sha256 却宣称 macOS 完成」（v0.6.37 事故）；
  - 发布平台 ready ⟺ 其覆盖工件类中存在 required 工件（sha 完整性由 finalize
    下载实测保证，不由 manifest 自证）。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MANIFEST_NAME = "release-artifacts-manifest.json"
SCHEMA_VERSION = 1
RELEASE_PLATFORMS = ("linux_x86_64", "linux_aarch64", "macos_arm64")
ARTIFACT_PLATFORMS = RELEASE_PLATFORMS + ("any", "linux")
STATUS_VALUES = ("ready", "pending", "absent")

# 发布平台 ← 工件平台类 的覆盖关系（推导规则见模块 docstring）。
PLATFORM_COVERAGE = {
    "linux_x86_64": frozenset({"any", "linux"}),
    "linux_aarch64": frozenset({"any", "linux"}),
    "macos_arm64": frozenset({"macos_arm64"}),
}

# 缺项清单中的“期望文件名”提示（<ver> 为版本占位）。
EXPECTED_FILE_HINTS = {
    "any": ("llm_first_loop-<ver>-py3-none-any.whl", "llm_first_loop-<ver>.tar.gz"),
    "linux": ("install_linux.sh", "uninstall_linux.sh"),
    "macos_arm64": ("LFL-<ver>-macos-arm64*.pkg",),
}

_MACOS_RE = re.compile(r"macos|darwin|\.pkg$|\.dmg$", re.IGNORECASE)
_LINUX_NAME_RE = re.compile(r"linux", re.IGNORECASE)
_OPTIONAL_PATTERNS = (
    re.compile(r"\.sha256$", re.IGNORECASE),
    re.compile(r"-smoke\.json$", re.IGNORECASE),
    re.compile(r"^sha256sums$", re.IGNORECASE),
)

BODY_BEGIN = "<!-- LFL-RELEASE-STATUS:BEGIN (machine-readable; scripts/release_finalize.py 维护) -->"
BODY_END = "<!-- LFL-RELEASE-STATUS:END -->"
_BODY_BLOCK_RE = re.compile(re.escape(BODY_BEGIN) + r".*?" + re.escape(BODY_END), re.DOTALL)
# latest/最新可用性承诺检测：只在“声明用户应取最新版/最新可用”的语义上命中
# （仅诊断上报、不阻断，宁漏勿误伤）：
#   英文 a) 取用类动词引导 latest release/version（download/get/use/... the latest version）；
#   英文 b) latest release/version + available 的可用性宣告（如 "latest release available now"）；
#   中文   最新可用 / 最新版(本) / 视为最新 / 作为最新。
# 纯描述性提及不命中（"the latest release notes"、"see the latest changes"、"最新一次提交"）。
_LATEST_CLAIM_RE = re.compile(
    r"\b(?:download|get|use|install|grab|fetch|upgrade[ \t]+to|switch[ \t]+to)\b"
    r"[^.\n]{0,48}?\blatest[ \t]+(?:release|version|build)s?\b"
    r"|\blatest[ \t]+(?:release|version|build)s?\b[^.\n]{0,40}?(?:is[ \t]+)?(?:now[ \t]+)?available"
    r"|最新可用|最新版(?!权)|视为最新|作为最新",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"v[A-Za-z0-9][A-Za-z0-9._+\-]*")

EXIT_OK = 0
EXIT_MANIFEST_INVALID = 2
EXIT_PLATFORM_NOT_READY = 3
EXIT_ARTIFACT_MISMATCH = 4
EXIT_RELEASE_ERROR = 5
EXIT_GUARD = 6


# ---------------------------------------------------------------- 分类与推导


def classify_platform(name: str) -> str:
    """文件名 → 工件平台类（macos_arm64 / linux / any）。"""
    if _MACOS_RE.search(name):
        return "macos_arm64"
    if _LINUX_NAME_RE.search(name):
        return "linux"
    return "any"


def is_required_artifact(name: str) -> bool:
    """辅助性工件（校验和/冒烟报告）不参与平台 ready 判定。"""
    return not any(p.search(name) for p in _OPTIONAL_PATTERNS)


def platform_has_required(artifacts, platform: str) -> bool:
    return any(
        isinstance(a, dict)
        and a.get("platform") in PLATFORM_COVERAGE[platform]
        and a.get("required")
        for a in artifacts
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    # time.gmtime（而非 datetime.UTC）：兼容签名机可能存在的 py3.9 系统 python3。
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------- manifest 构造


def build_manifest(file_facts, tag: str, commit_sha: str, absent_platforms=()):
    """file_facts: {name: (sha256, size_bytes)}；生成确定性排序的 manifest v1。"""
    absent = {p for p in absent_platforms if p in RELEASE_PLATFORMS}
    artifacts = [
        {
            "name": name,
            "platform": classify_platform(name),
            "sha256": file_facts[name][0],
            "size_bytes": file_facts[name][1],
            "required": is_required_artifact(name),
        }
        for name in sorted(file_facts)
    ]
    platform_status = {}
    for platform in RELEASE_PLATFORMS:
        if platform in absent:
            platform_status[platform] = "absent"
        elif platform_has_required(artifacts, platform):
            platform_status[platform] = "ready"
        else:
            platform_status[platform] = "pending"
    return {
        "schema_version": SCHEMA_VERSION,
        "tag": tag,
        "commit_sha": commit_sha,
        "generated_at": utc_now_iso(),
        "artifacts": artifacts,
        "platform_status": platform_status,
        "platform_policy": {
            "coverage": {p: sorted(c) for p, c in PLATFORM_COVERAGE.items()},
            "optional_artifact_patterns": [r"\.sha256$", r"-smoke\.json$", r"^SHA256SUMS$"],
            "required_platforms_default": list(RELEASE_PLATFORMS),
            "note": "ready ⟺ 覆盖工件类中存在 required 工件；sha256 由 finalize 下载实测比对",
        },
    }


def manifest_bytes(manifest) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def validate_manifest(manifest, tag: str):
    """结构/一致性校验；返回问题行列表（空列表 = 通过）。"""
    problems = []
    if not isinstance(manifest, dict):
        return ["manifest 顶层不是 JSON 对象"]
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version 应为 {SCHEMA_VERSION}，实际 {manifest.get('schema_version')!r}")
    if manifest.get("tag") != tag:
        problems.append(f"tag 不符: manifest={manifest.get('tag')!r} 请求={tag!r}")
    if not str(manifest.get("commit_sha", "")):
        problems.append("commit_sha 缺失")
    if not str(manifest.get("generated_at", "")):
        problems.append("generated_at 缺失")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append("artifacts 必须是非空数组")
        artifacts = []
    names = set()
    for idx, art in enumerate(artifacts):
        if not isinstance(art, dict):
            problems.append(f"artifacts[{idx}] 不是对象")
            continue
        missing_keys = [k for k in ("name", "platform", "sha256", "size_bytes", "required") if k not in art]
        if missing_keys:
            problems.append(f"artifacts[{idx}] 缺字段 {missing_keys}")
            continue
        if art["platform"] not in ARTIFACT_PLATFORMS:
            problems.append(f"artifacts[{idx}].platform 非法: {art['platform']!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(art["sha256"])):
            problems.append(f"artifacts[{idx}].sha256 非法: {art['sha256']!r}")
        if art["name"] in names:
            problems.append(f"artifacts[{idx}].name 重复: {art['name']}")
        names.add(art["name"])
    status = manifest.get("platform_status")
    if not isinstance(status, dict) or set(status) != set(RELEASE_PLATFORMS):
        problems.append(f"platform_status 键必须恰好是 {list(RELEASE_PLATFORMS)}")
    else:
        for platform in RELEASE_PLATFORMS:
            value = status[platform]
            if value not in STATUS_VALUES:
                problems.append(f"platform_status.{platform} 非法: {value!r}")
                continue
            has_required = platform_has_required(artifacts, platform)
            if value == "ready" and not has_required:
                problems.append(f"platform_status.{platform}=ready 但无 required 工件支撑（与 artifacts 不一致）")
            if value != "ready" and has_required:
                problems.append(
                    f"platform_status.{platform}={value!r} 但 artifacts 存在 required 工件（疑似手改/过期，请重新 sync）"
                )
    return problems


# ------------------------------------------------------------------- 正文状态块


def _platform_line(platform_status) -> str:
    label = {
        "linux_x86_64": "Linux x86_64",
        "linux_aarch64": "Linux aarch64",
        "macos_arm64": "macOS arm64",
    }
    mark = {"ready": "✅ready", "pending": "⏳pending", "absent": "➖absent"}
    return " / ".join(f"{label[p]} {mark[platform_status[p]]}" for p in RELEASE_PLATFORMS)


def _wrap_block(payload, human: str) -> str:
    return (
        f"{BODY_BEGIN}\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n"
        f"{human}\n{BODY_END}"
    )


def render_draft_block(manifest) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tag": manifest["tag"],
        "state": "draft",
        "latest_ready": False,
        "platform_status": manifest["platform_status"],
        "manifest": MANIFEST_NAME,
    }
    human = (
        f"**状态（draft）**：{_platform_line(manifest['platform_status'])}。"
        "draft 是默认持久中间态：全平台 ready 且 manifest 逐资产 sha256 实测相符前，"
        f"本版本不作为最新可用版本。权威状态见资产 {MANIFEST_NAME}；转正由 Finalize Release "
        "workflow 机械判据触发（不人工点 publish）。"
    )
    return _wrap_block(payload, human)


def render_published_block(tag: str, platform_status, manifest_sha256: str) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tag": tag,
        "state": "published",
        "latest_ready": True,
        "platform_status": platform_status,
        "manifest": MANIFEST_NAME,
        "manifest_sha256": manifest_sha256,
        "promoted_at": utc_now_iso(),
    }
    human = (
        f"**状态（published）**：{_platform_line(platform_status)}；"
        f"全部资产 sha256 已与 {MANIFEST_NAME} 逐一实测相符，本版本可作为最新可用版本。"
    )
    return _wrap_block(payload, human)


def replace_status_block(body: str, new_block: str) -> str:
    """幂等：已有状态块则原位替换首个并清除多余残留块；否则置顶追加。"""
    if BODY_BEGIN in body and BODY_END in body:
        replaced = [False]

        def _put_first(_m):
            if replaced[0]:
                return ""  # 残留的旧状态块：清除，只在首个块位置写入新块（幂等收敛）
            replaced[0] = True
            return new_block

        return _BODY_BLOCK_RE.sub(_put_first, body)
    if not body.strip():
        return new_block
    return f"{new_block}\n\n{body.rstrip()}"


def find_latest_claims(body: str):
    """在状态块之外扫描 latest/最新可用性承诺（仅诊断上报，不修改正文）。"""
    stripped = _BODY_BLOCK_RE.sub("", body)
    return sorted({m.group(0) for m in _LATEST_CLAIM_RE.finditer(stripped)})


def _report_latest_violation(body: str) -> None:
    claims = find_latest_claims(body)
    if claims:
        print(f"[违规][latest] 平台未全绿，但正文出现可用性承诺词: {claims}（正文不会被本脚本修改；请人工清理后再重试）")


# ---------------------------------------------------------------------- transport


class GhError(RuntimeError):
    pass


class GhCli:
    """gh CLI 封装（唯一网络出口；--self-check 用 FakeGh 注入替代）。"""

    def __init__(self, repo: str):
        self.repo = repo

    def _run(self, *args) -> str:
        cmd = ["gh", *args, "--repo", self.repo]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise GhError(f"gh CLI 不可用: {exc}") from exc
        if proc.returncode != 0:
            raise GhError(
                f"命令失败(exit={proc.returncode}): {' '.join(cmd)}\nstderr: {proc.stderr.strip()}"
            )
        return proc.stdout

    def view(self, tag: str):
        out = self._run(
            "release", "view", tag, "--json", "isDraft,assets,body,targetCommitish,url"
        )
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise GhError(f"gh release view 输出不可解析: {exc}") from exc

    def download_all(self, tag: str, dest_dir: Path) -> None:
        self._run("release", "download", tag, "--dir", str(dest_dir), "--clobber")

    def upload(self, tag: str, path: Path) -> None:
        self._run("release", "upload", tag, str(path), "--clobber")

    def edit_body(self, tag: str, body_path: Path) -> None:
        self._run("release", "edit", tag, "--notes-file", str(body_path))

    def undraft(self, tag: str) -> None:
        self._run("release", "edit", tag, "--draft=false")


class FakeGh:
    """内存版 Release 模型（--self-check 专用；不触网、不调 gh）。接口同 GhCli。"""

    def __init__(self, assets, draft=True, body="", target_commitish=None, url="https://example.invalid/r"):
        self.assets = dict(assets)
        self.draft = draft
        self.body = body
        self.target_commitish = target_commitish or "f" * 40
        self.url = url
        self.mutations = []

    def view(self, tag: str):
        return {
            "isDraft": self.draft,
            "assets": [{"name": name, "size": len(blob)} for name, blob in sorted(self.assets.items())],
            "body": self.body,
            "targetCommitish": self.target_commitish,
            "url": self.url,
            "tagName": tag,
        }

    def download_all(self, tag: str, dest_dir: Path) -> None:
        dest = Path(dest_dir)
        for name, blob in self.assets.items():
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)

    def upload(self, tag: str, path: Path) -> None:
        data = Path(path).read_bytes()
        self.assets[Path(path).name] = data
        self.mutations.append(("upload", Path(path).name))

    def edit_body(self, tag: str, body_path: Path) -> None:
        self.body = Path(body_path).read_text(encoding="utf-8")
        self.mutations.append(("edit_body",))

    def undraft(self, tag: str) -> None:
        self.draft = False
        self.mutations.append(("undraft",))


# ------------------------------------------------------------------------ 命令


def validate_tag_or_die(tag: str) -> str:
    # 不含斜杠等字符——保证与 release.yml 顶层 concurrency 组名
    # release-refs/tags/<tag> 逐字符一致（single-writer 串行组不被绕开）。
    if not _TAG_RE.fullmatch(tag):
        print(f"[guard] 非法 tag {tag!r}（需形如 v0.6.38；斜杠/特殊字符会破坏串行组名等价）")
        sys.exit(EXIT_GUARD)
    return tag


def collect_local_facts(from_dir: str):
    directory = Path(from_dir)
    if not directory.is_dir():
        raise GhError(f"--from-dir 不存在: {directory}")
    facts = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name != MANIFEST_NAME:
            facts[path.name] = (sha256_file(path), path.stat().st_size)
    if not facts:
        raise GhError(f"--from-dir 目录为空: {directory}")
    return facts


def cmd_manifest_local(from_dir, tag, commit_sha, absent_platforms, out, body_out) -> int:
    facts = collect_local_facts(from_dir)
    manifest = build_manifest(facts, tag, commit_sha, absent_platforms)
    out_path = Path(out) if out else Path(from_dir) / MANIFEST_NAME
    body_path = Path(body_out) if body_out else Path(from_dir) / "release-body-status.md"
    out_path.write_bytes(manifest_bytes(manifest))
    body_path.write_text(render_draft_block(manifest) + "\n", encoding="utf-8")
    print(f"[manifest] 已生成 {out_path}（{len(manifest['artifacts'])} 个工件；正文状态块 → {body_path}）")
    for platform in RELEASE_PLATFORMS:
        print(f"[manifest] platform_status.{platform} = {manifest['platform_status'][platform]}")
    return EXIT_OK


def sync_manifest_from_release(gh, tag: str, absent_platforms=()) -> int:
    rel = gh.view(tag)
    if not rel.get("isDraft", False):
        print(f"[guard] {tag} 不是 draft（已公开），拒绝改写 manifest；如需变更请走新 tag。")
        return EXIT_GUARD
    with tempfile.TemporaryDirectory(prefix="lfl-release-sync-") as tmp:
        tmpdir = Path(tmp)
        gh.download_all(tag, tmpdir)
        old_manifest = None
        if (tmpdir / MANIFEST_NAME).is_file():
            try:
                old_manifest = json.loads((tmpdir / MANIFEST_NAME).read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                old_manifest = None
        facts = {}
        for path in sorted(tmpdir.rglob("*")):
            if path.is_file() and path.name != MANIFEST_NAME:
                facts[path.relative_to(tmpdir).as_posix()] = (sha256_file(path), path.stat().st_size)
        if not facts:
            print("[guard] Release 上没有任何工件资产，拒绝生成空 manifest。")
            return EXIT_GUARD
        manifest = build_manifest(facts, tag, str(rel.get("targetCommitish", "")), absent_platforms)
        if isinstance(old_manifest, dict):
            old_map = {a.get("name"): a.get("sha256") for a in old_manifest.get("artifacts", []) if isinstance(a, dict)}
            for art in manifest["artifacts"]:
                prev = old_map.get(art["name"])
                if prev is not None and prev != art["sha256"]:
                    print(f"[manifest][警报] 资产 {art['name']} sha256 与上一版 manifest 不同（疑似被替换/重传），已按当前实测记录")
            for name in sorted(set(old_map) - {a["name"] for a in manifest["artifacts"]}):
                if name:
                    print(f"[manifest][警报] 上一版 manifest 中的资产 {name} 已不在 Release 上")
        manifest_path = tmpdir / MANIFEST_NAME
        manifest_path.write_bytes(manifest_bytes(manifest))
        gh.upload(tag, manifest_path)
        print(f"[manifest] 已按 Release 实际资产重生成并回传 {MANIFEST_NAME}（{len(manifest['artifacts'])} 个工件）")
        for platform in RELEASE_PLATFORMS:
            print(f"[manifest] platform_status.{platform} = {manifest['platform_status'][platform]}")
        return EXIT_OK


def apply_status_block(gh, tag: str, block_file: str) -> int:
    rel = gh.view(tag)
    if not rel.get("isDraft", False):
        print(f"[guard] {tag} 不是 draft，拒绝改写正文（published Release 对本脚本只读）。")
        return EXIT_GUARD
    block = Path(block_file).read_text(encoding="utf-8").strip()
    old_body = rel.get("body", "")
    new_body = replace_status_block(old_body, block)
    if new_body == old_body:
        print("[body] 正文状态块已是最新，未修改（幂等）。")
        return EXIT_OK
    with tempfile.TemporaryDirectory(prefix="lfl-release-body-") as tmp:
        body_path = Path(tmp) / "body.md"
        body_path.write_text(new_body, encoding="utf-8")
        gh.edit_body(tag, body_path)
    print("[body] 已将机器可读平台状态块写入 Release 正文（置顶/原位替换）。")
    return EXIT_OK


def finalize_release(gh, tag: str, require_platforms=RELEASE_PLATFORMS) -> int:
    rel = gh.view(tag)
    if not rel.get("isDraft", False):
        print(f"[幂等] {tag} 已是 published（isDraft=false），无需转正；未执行任何写操作。")
        return EXIT_OK
    asset_names = [a["name"] for a in rel.get("assets", [])]
    if MANIFEST_NAME not in asset_names:
        print(f"[缺项][manifest] Release 缺少资产 {MANIFEST_NAME}"
              "（期望：release.yml 创建 draft 时上传，或 macOS 签名机 manifest 子命令回传）")
        print("[finalize] 保持 draft，未做任何修改。")
        return EXIT_MANIFEST_INVALID
    with tempfile.TemporaryDirectory(prefix="lfl-release-finalize-") as tmp:
        tmpdir = Path(tmp)
        gh.download_all(tag, tmpdir)
        try:
            manifest = json.loads((tmpdir / MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[缺项][manifest] manifest 资产无法读取/解析: {exc}")
            print("[finalize] 保持 draft，未做任何修改。")
            return EXIT_MANIFEST_INVALID
        invalid = validate_manifest(manifest, tag)
        if invalid:
            for line in invalid:
                print(f"[缺项][manifest] {line}")
            print("[finalize] 保持 draft，未做任何修改。")
            return EXIT_MANIFEST_INVALID

        # 判据 b/c：逐资产实测 sha256/size + 资产集一致。
        problems = []
        declared = {a["name"] for a in manifest["artifacts"]}
        for art in manifest["artifacts"]:
            path = tmpdir / art["name"]
            if not path.is_file():
                problems.append(f"资产缺失: {art['name']}（manifest 已申报，Release 上不存在）")
                continue
            actual_sha = sha256_file(path)
            actual_size = path.stat().st_size
            if actual_sha != art["sha256"]:
                problems.append(f"sha256 不符: {art['name']} manifest={art['sha256']} 实测={actual_sha}")
            if actual_size != art["size_bytes"]:
                problems.append(f"size 不符: {art['name']} manifest={art['size_bytes']} 实测={actual_size}")
        for name in asset_names:
            if name != MANIFEST_NAME and name not in declared:
                problems.append(f"多余资产: {name}（manifest 未申报；请先 manifest 子命令 sync 或移除该资产）")
        if problems:
            for line in problems:
                print(f"[拒绝][sha256/资产集] {line}")
            _report_latest_violation(rel.get("body", ""))
            print("[finalize] 保持 draft，未做任何修改。")
            return EXIT_ARTIFACT_MISMATCH

        # 判据 a：所有 required 平台 ready。
        require = tuple(require_platforms) or RELEASE_PLATFORMS
        not_ready = [p for p in require if manifest["platform_status"].get(p) != "ready"]
        if not_ready:
            for platform in not_ready:
                status = manifest["platform_status"].get(platform, "<缺键>")
                hints = "、".join(
                    hint
                    for cls in sorted(PLATFORM_COVERAGE[platform])
                    for hint in EXPECTED_FILE_HINTS[cls]
                )
                print(f"[缺项][平台] {platform} 状态 = {status}（未 ready）")
                print(f"[缺项][平台] {platform} 期望工件: {hints}（required 工件不在场或未申报）")
            _report_latest_violation(rel.get("body", ""))
            print("[finalize] 保持 draft，未做任何修改（draft 是默认持久中间态）。")
            return EXIT_PLATFORM_NOT_READY

        # 全绿：先重写正文状态块（published/latest_ready=true），再 --draft=false。
        manifest_sha = sha256_file(tmpdir / MANIFEST_NAME)
        new_body = replace_status_block(
            rel.get("body", ""), render_published_block(tag, manifest["platform_status"], manifest_sha)
        )
        body_path = tmpdir / "release-body-published.md"
        body_path.write_text(new_body, encoding="utf-8")
        gh.edit_body(tag, body_path)
        gh.undraft(tag)
        print(f"[转正] {tag}: platform_status = {json.dumps(manifest['platform_status'], ensure_ascii=False)}")
        print(f"[转正] manifest_sha256 = {manifest_sha}（逐资产实测相符）")
        print(f"[转正] 已先重写正文状态块为 published，再执行 --draft=false：{rel.get('url')}")
        return EXIT_OK


# ---------------------------------------------------------------------- 自检


def _make_ci_dist(dist_dir: Path) -> None:
    files = {
        "llm_first_loop-0.6.38-py3-none-any.whl": b"wheel-bytes-0.6.38",
        "llm_first_loop-0.6.38.tar.gz": b"sdist-bytes-0.6.38",
        "install_linux.sh": b"#!/bin/sh\nexit 0\n",
        "uninstall_linux.sh": b"#!/bin/sh\nexit 0\n",
        "installation-smoke.json": b'{"ok": true}',
        "linux-installer-smoke.json": b'{"ok": true}',
        "SHA256SUMS": b"fake-checksums\n",
    }
    dist_dir.mkdir(parents=True, exist_ok=True)
    for name, blob in files.items():
        (dist_dir / name).write_bytes(blob)


def _macos_files():
    return {
        "LFL-0.6.38-macos-arm64-signed.pkg": b"PKG-SIGNED-" + b"y" * 8192,
        "LFL-0.6.38-macos-arm64-signed.pkg.sha256": b"sidecar-checksum\n",
    }


def _draft_fake_from_dist(dist_dir: Path, tag="v0.6.38", commit="a" * 40):
    facts = collect_local_facts(str(dist_dir))
    manifest = build_manifest(facts, tag, commit)
    assets = {name: (dist_dir / name).read_bytes() for name in facts}
    assets[MANIFEST_NAME] = manifest_bytes(manifest)
    return FakeGh(assets, draft=True, body=render_draft_block(manifest), target_commitish=commit)


def _green_fake(tmp: Path, name: str):
    """CI 建 draft → 签名机上传 .pkg → manifest sync 之后的“全绿”状态。"""
    dist = tmp / f"{name}-dist"
    _make_ci_dist(dist)
    fake = _draft_fake_from_dist(dist)
    fake.assets.update(_macos_files())
    code, text = _capture(sync_manifest_from_release, fake, "v0.6.38")
    assert code == EXIT_OK, f"sync 失败:\n{text}"
    synced = json.loads(fake.assets[MANIFEST_NAME].decode("utf-8"))
    assert synced["platform_status"]["macos_arm64"] == "ready", synced["platform_status"]
    return fake


def _capture(fn, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = fn(*args, **kwargs)
    text = buffer.getvalue()
    sys.stdout.write(text)
    return code, text


def _scenario_green_promote(tmp: Path) -> None:
    fake = _green_fake(tmp, "s1")
    assert fake.body and BODY_BEGIN in fake.body
    assert '"state": "draft"' in fake.body and '"latest_ready": false' in fake.body
    code, text = _capture(finalize_release, fake, "v0.6.38", RELEASE_PLATFORMS)
    assert code == EXIT_OK, f"期望转正成功:\n{text}"
    assert not fake.draft, "转正后应 isDraft=false"
    assert fake.mutations[-1] == ("undraft",), fake.mutations
    assert ("edit_body",) in fake.mutations, "转正前应先重写正文状态块"
    assert '"state": "published"' in fake.body and '"latest_ready": true' in fake.body
    assert '"macos_arm64": "ready"' in fake.body


def _scenario_missing_macos_stay_draft(tmp: Path) -> None:
    dist = tmp / "s2-dist"
    _make_ci_dist(dist)
    fake = _draft_fake_from_dist(dist)
    code, text = _capture(finalize_release, fake, "v0.6.38", RELEASE_PLATFORMS)
    assert code == EXIT_PLATFORM_NOT_READY, f"期望平台未就绪拒绝:\n{text}"
    assert fake.draft and fake.mutations == [], "必须保持 draft 且零写操作"
    assert "macos_arm64" in text and "pending" in text, text
    assert "macos-arm64*.pkg" in text, f"缺项清单应给出期望文件名:\n{text}"
    assert "保持 draft" in text


def _scenario_sha_mismatch_reject(tmp: Path) -> None:
    fake = _green_fake(tmp, "s3")
    fake.assets["LFL-0.6.38-macos-arm64-signed.pkg"] = b"TAMPERED-PKG-BYTES"
    baseline = list(fake.mutations)  # sync 阶段的 manifest 上传不计入 finalize 写操作
    code, text = _capture(finalize_release, fake, "v0.6.38", RELEASE_PLATFORMS)
    assert code == EXIT_ARTIFACT_MISMATCH, f"期望 sha256 不符拒绝:\n{text}"
    assert fake.draft and fake.mutations == baseline, "必须保持 draft 且零新增写操作"
    assert "sha256 不符" in text and "LFL-0.6.38-macos-arm64-signed.pkg" in text, text


def _scenario_manifest_missing_reject(tmp: Path) -> None:
    fake = _green_fake(tmp, "s4")
    del fake.assets[MANIFEST_NAME]
    baseline = list(fake.mutations)
    code, text = _capture(finalize_release, fake, "v0.6.38", RELEASE_PLATFORMS)
    assert code == EXIT_MANIFEST_INVALID, f"期望 manifest 缺失拒绝:\n{text}"
    assert fake.draft and fake.mutations == baseline, "必须保持 draft 且零新增写操作"
    assert MANIFEST_NAME in text and "保持 draft" in text, text


def _scenario_idempotent_replay(tmp: Path) -> None:
    fake = _green_fake(tmp, "s5")
    code, text = _capture(finalize_release, fake, "v0.6.38", RELEASE_PLATFORMS)
    assert code == EXIT_OK and not fake.draft, text
    baseline = len(fake.mutations)
    code2, text2 = _capture(finalize_release, fake, "v0.6.38", RELEASE_PLATFORMS)
    assert code2 == EXIT_OK, f"重放应幂等成功:\n{text2}"
    assert "已是 published" in text2 and "幂等" in text2, text2
    assert len(fake.mutations) == baseline, "重放不得产生新写操作"
    code3, text3 = _capture(sync_manifest_from_release, fake, "v0.6.38")
    assert code3 == EXIT_GUARD, f"published 后 sync 应被 guard 拒绝:\n{text3}"


_LATEST_CLAIM_POSITIVES = (
    "download the latest version",
    "请下载最新版本",
    "latest release available now",
    "get the latest release",
    "建议使用最新版",
)
_LATEST_CLAIM_NEGATIVES = (
    "the latest release notes",
    "see the latest changes",
    "最新一次提交",
    "the latest version of the changelog",
)


def _scenario_latest_claim_detection(tmp: Path) -> None:
    for sample in _LATEST_CLAIM_POSITIVES:
        claims = find_latest_claims(sample)
        assert claims, f"正样本应命中可用性承诺: {sample!r}"
    for sample in _LATEST_CLAIM_NEGATIVES:
        claims = find_latest_claims(sample)
        assert not claims, f"负样本不应误伤（宁漏勿误伤）: {sample!r} → {claims}"


def _scenario_body_multi_block_converge(tmp: Path) -> None:
    dist = tmp / "s6-dist"
    _make_ci_dist(dist)
    fake = _draft_fake_from_dist(dist)
    manifest = json.loads(fake.assets[MANIFEST_NAME].decode("utf-8"))
    new_block = render_draft_block(manifest)
    stale_published = render_published_block("v0.6.38", manifest["platform_status"], "f" * 64)
    stale_old_tag = new_block.replace("v0.6.38", "v0.6.37")  # 旧 tag 残留块，内容与待写块不同
    fake.body = stale_published + "\n\n安装说明正文（块外文字应保留）。\n\n" + stale_old_tag
    block_file = tmp / "s6-block.md"
    block_file.write_text(new_block + "\n", encoding="utf-8")
    for attempt in (1, 2):
        code, text = _capture(apply_status_block, fake, "v0.6.38", str(block_file))
        assert code == EXIT_OK, f"第 {attempt} 次 body 写入应成功:\n{text}"
    assert fake.body.count(BODY_BEGIN) == 1 and fake.body.count(BODY_END) == 1, (
        f"两次写入后应仅剩一个状态块:\n{fake.body}"
    )
    assert fake.body.startswith(new_block), "新块应写入首个块的原位置"
    assert "安装说明正文（块外文字应保留）" in fake.body, "块外正文必须保留"
    assert "v0.6.37" not in fake.body and '"state": "published"' not in fake.body
    assert fake.mutations.count(("edit_body",)) == 1, f"第二次写入应幂等零写: {fake.mutations}"


def _scenario_body_published_guard(tmp: Path) -> None:
    dist = tmp / "s7-dist"
    _make_ci_dist(dist)
    fake = _draft_fake_from_dist(dist)
    fake.draft = False  # FakeGh.view() 返回 isDraft=False（已 published）
    block_file = tmp / "s7-block.md"
    block_file.write_text(fake.body + "\n", encoding="utf-8")
    before = fake.body
    code, text = _capture(apply_status_block, fake, "v0.6.38", str(block_file))
    assert code == EXIT_GUARD, f"published 后 body 写入应被 guard 拒绝(exit={EXIT_GUARD}):\n{text}"
    assert ("edit_body",) not in fake.mutations, f"必须零写操作: {fake.mutations}"
    assert fake.body == before, "published Release 对本脚本只读"
    assert "不是 draft" in text and "拒绝改写正文" in text, text


def self_check() -> int:
    scenarios = [
        ("S1 全绿转正（sync→finalize，先改正文再 undraft）", _scenario_green_promote),
        ("S2 缺 macos 保持 draft + 缺项清单", _scenario_missing_macos_stay_draft),
        ("S3 sha256 不符拒绝", _scenario_sha_mismatch_reject),
        ("S4 manifest 缺失拒绝", _scenario_manifest_missing_reject),
        ("S5 重复执行幂等（published 重放零写）", _scenario_idempotent_replay),
        ("S6 latest 承诺检测正/负样本（宁漏勿误伤）", _scenario_latest_claim_detection),
        ("S7 正文双状态块残留两次写入收敛为一块", _scenario_body_multi_block_converge),
        ("S8 published Release body guard 拒绝且零写", _scenario_body_published_guard),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix="lfl-finalize-selfcheck-") as tmp:
        tmpdir = Path(tmp)
        for name, fn in scenarios:
            print(f"===== 场景 {name} =====")
            try:
                fn(tmpdir)
                results.append((name, True, ""))
                print(f"PASS [{name}]")
            except AssertionError as exc:
                results.append((name, False, str(exc)))
                print(f"FAIL [{name}] {exc}")
            print()
    for name, ok, msg in results:
        print(f"{'PASS' if ok else 'FAIL'}\t{name}\t{msg}")
    failed = [r for r in results if not r[1]]
    print(f"\nself-check 汇总: {len(results) - len(failed)}/{len(results)} 场景通过")
    return EXIT_OK if not failed else 1


# ------------------------------------------------------------------------ CLI


def run_guarded(fn, *args, **kwargs) -> int:
    try:
        return fn(*args, **kwargs)
    except GhError as exc:
        print(f"[错误][gh] {exc}")
        return EXIT_RELEASE_ERROR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release_finalize.py",
        description="draft-first 发布语义：平台工件 manifest + 机械转正门禁（详见模块 docstring）",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="离线自检：全绿转正/缺 macos 保持 draft/sha256 不符/manifest 缺失/幂等重放/latest 承诺正负样本/双状态块收敛/published body guard",
    )
    sub = parser.add_subparsers(dest="command")

    p_manifest = sub.add_parser(
        "manifest",
        help="生成 manifest（--from-dir 本地生成；缺省按 Release 实际资产重生成并回传）",
    )
    p_manifest.add_argument("--tag", required=True)
    p_manifest.add_argument("--from-dir", help="本地工件目录（CI: dist/）")
    p_manifest.add_argument("--commit-sha", default="")
    p_manifest.add_argument("--out", help=f"manifest 输出路径（默认 <from-dir>/{MANIFEST_NAME}）")
    p_manifest.add_argument("--body-out", help="正文状态块输出路径（默认 <from-dir>/release-body-status.md）")
    p_manifest.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p_manifest.add_argument(
        "--platform-absent",
        action="append",
        default=[],
        choices=RELEASE_PLATFORMS,
        help="显式声明某平台本版本不发布（absent）；默认未见 required 工件即 pending",
    )

    p_body = sub.add_parser("body", help="把状态块幂等写入 Release 正文（置顶；非 draft 拒绝）")
    p_body.add_argument("--tag", required=True)
    p_body.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p_body.add_argument("--block-file", required=True)

    p_fin = sub.add_parser("finalize", help="机械判据转正：全平台 ready + 逐资产 sha256 相符才 --draft=false")
    p_fin.add_argument("--tag", required=True)
    p_fin.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    p_fin.add_argument(
        "--require-platform",
        nargs="+",
        default=list(RELEASE_PLATFORMS),
        choices=RELEASE_PLATFORMS,
        help="required 平台集合（默认三平台全要求；收窄需显式授权并留痕）",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if args.command is None:
        parser.print_help()
        return 2
    try:
        tag = validate_tag_or_die(args.tag)
        if args.command == "manifest":
            if args.from_dir:
                return run_guarded(
                    cmd_manifest_local,
                    args.from_dir,
                    tag,
                    args.commit_sha,
                    tuple(args.platform_absent),
                    args.out,
                    args.body_out,
                )
            if not args.repo:
                parser.error("Release 同步模式需要 --repo（或设 GITHUB_REPOSITORY）")
            return run_guarded(sync_manifest_from_release, GhCli(args.repo), tag, tuple(args.platform_absent))
        if args.command == "body":
            if not args.repo:
                parser.error("body 模式需要 --repo（或设 GITHUB_REPOSITORY）")
            return run_guarded(apply_status_block, GhCli(args.repo), tag, args.block_file)
        if args.command == "finalize":
            if not args.repo:
                parser.error("finalize 需要 --repo（或设 GITHUB_REPOSITORY）")
            return run_guarded(finalize_release, GhCli(args.repo), tag, tuple(args.require_platform))
    except SystemExit as exc:  # validate_tag_or_die 的 guard 退出
        return int(exc.code or EXIT_OK)
    return 2


if __name__ == "__main__":
    sys.exit(main())
