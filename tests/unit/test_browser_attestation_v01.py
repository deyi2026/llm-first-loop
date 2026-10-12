"""S3b：R3 绑定 attestation（DESIGN-20261005 v4 §4.3；机制=S0 结论 ② host 侧进程证据）。

1. 判定器 v2：argv 两形态/relative/symlink realpath 三态/树内指回/PATHS 三态
2. BindingPolicy：enforce 拒 real / shadow 只记录 / allow_real 放行
3. host 集成：直连默认态（policy 缺省 deny_real）real verdict ⇒ 拒绝绑定
4. coordinator attestation 一致性：verdict 不一致 ⇒ 拒绝
5. 机制 fail-closed：死端口 ⇒ verdict=real
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from llm_loop.browser import attestation as attestation_mod
from llm_loop.browser.attestation import (
    AttestationVerdict,
    BindingPolicy,
    attest_port,
    attest_debug_url,
    builtin_default_trees,
    classify_user_data_dir,
    extract_user_data_dir_value,
    resolve_profile_trees,
    sha256_argv,
)
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.channel_binding import BrowserChannelBindingCoordinator

TREES = builtin_default_trees()
OUTSIDE = "/tmp/attest-outside-profile"  # 不在默认树内


def _v(verdict: str, sha: str = "a" * 64) -> AttestationVerdict:
    return AttestationVerdict(
        verdict=verdict, user_data_dir="/tmp/x", argv_sha256=sha,
        argv=(), detail="stub",
    )


# ── 1. 判定器 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--user-data-dir=/tmp/p", "about:blank"], "/tmp/p"),
        (["chrome", "--user-data-dir", "/tmp/p2", "--headless=new"], "/tmp/p2"),
        (["chrome", "--user-data-dir=/a", "--user-data-dir", "/b"], "/b"),  # 混合形态取最后
        (["chrome", "--headless=new"], None),
    ],
)
def test_extract_user_data_dir_two_forms(argv, expected):
    assert extract_user_data_dir_value(argv) == expected


def test_extract_preserves_path_with_spaces():
    argv = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--user-data-dir=/tmp/dir with space", "about:blank"]
    assert extract_user_data_dir_value(argv) == "/tmp/dir with space"


def test_classify_none_and_relative_fail_closed():
    assert classify_user_data_dir(None, TREES)[0] == "real"
    assert classify_user_data_dir("relative/path", TREES)[0] == "real"


def test_classify_inside_default_tree_is_real(tmp_path):
    tree = TREES[0]
    assert classify_user_data_dir(str(tree), TREES)[0] == "real"
    sub = tree / "Profile 5"
    assert classify_user_data_dir(str(sub), TREES)[0] == "real"


def test_classify_outside_is_dedicated(tmp_path):
    outside = tmp_path / "dedicated-profile"
    outside.mkdir()
    assert classify_user_data_dir(str(outside), TREES)[0] == "dedicated"


def test_classify_symlink_three_states(tmp_path):
    outside = tmp_path / "outside-real"
    outside.mkdir()
    link_outside = tmp_path / "link-outside"
    link_outside.symlink_to(outside, target_is_directory=True)
    v, _ = classify_user_data_dir(str(link_outside), TREES)
    assert v == "dedicated"

    # symlink 指回默认树内 ⇒ real
    tree = TREES[0]
    link_inside = tmp_path / "link-inside"
    link_inside.symlink_to(tree, target_is_directory=True)
    v2, _ = classify_user_data_dir(str(link_inside), TREES)
    assert v2 == "real"

    # 断裂 symlink（目标不存在）⇒ fail-closed real
    broken = tmp_path / "broken"
    broken.symlink_to(tmp_path / "no-such-target", target_is_directory=True)
    v3, detail = classify_user_data_dir(str(broken), TREES)
    assert v3 == "real"
    assert "fail-closed" in detail


def test_paths_three_states(tmp_path):
    assert resolve_profile_trees("") is not None
    assert resolve_profile_trees("none") is None
    extra = tmp_path / "extra-tree"
    extra.mkdir()
    trees = resolve_profile_trees(str(extra))
    assert trees is not None
    assert any(t == extra.resolve() for t in trees)
    assert len(trees) == len(TREES) + 1  # 内置 ∪ 追加，只增不替
    with pytest.raises(ValueError):
        resolve_profile_trees("relative/path")
    # none 档：一切值都 real
    assert classify_user_data_dir("/tmp/anything", None)[0] == "real"


def test_sha256_argv_deterministic():
    assert sha256_argv(["a", "b"]) == sha256_argv(["a", "b"])
    assert sha256_argv(["a", "b"]) != sha256_argv(["a b"])


# ── 2. BindingPolicy ────────────────────────────────────────────────────


def test_policy_enforce_refuses_real_without_allow():
    ok, reason = BindingPolicy.deny_real().check(_v("real"))
    assert ok is False and "fail-closed" in reason


def test_policy_default_constructor_is_fail_closed():
    policy = BindingPolicy()
    assert policy.allow_real is False
    ok, reason = policy.check(_v("real"))
    assert ok is False and "fail-closed" in reason


def test_policy_enforce_allows_real_with_ack():
    ok, reason = BindingPolicy.permit_real("digest123").check(_v("real"))
    assert ok is True and "digest123" in reason


def test_policy_shadow_never_refuses_but_records():
    ok, reason = BindingPolicy.deny_real(mode="shadow").check(_v("real"))
    assert ok is True and "shadow" in reason


def test_policy_dedicated_always_allowed():
    ok, _ = BindingPolicy.deny_real().check(_v("dedicated"))
    assert ok is True


# ── 3/4. host 集成 ──────────────────────────────────────────────────────


class _FakeWs:
    def __init__(self) -> None:
        self.pending: list[str] = []

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        if req["method"] == "Page.enable":
            result = {"result": {}}
        elif req["method"] == "Target.getTargetInfo":
            result = {"result": {"targetInfo": {"targetId": req["params"].get("targetId")}}}
        else:
            result = {"result": {"result": {"type": "undefined"}}}
        self.pending.append(json.dumps({"id": req["id"], **result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None: ...


def _perceive(*, policy=None, coord=None, attest):
    return CdpReadOnlyBrowserHost(
        "http://127.0.0.1:9222",
        target_id="t-1",
        http_get_json=lambda url: [{
            "id": "t-1", "type": "page", "url": "about:blank",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/t-1",
        }],
        http_get_version_dict=lambda url: {
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/uuid-1"},
        ws_connect=lambda url: _FakeWs(),
        binding_coordinator=coord,
        binding_policy=policy,
        attest_fn=lambda url: attest,
    )


def test_direct_entry_default_policy_refuses_real_chrome():
    """直连入口零改动默认态：verdict=real（无 --user-data-dir 的 Chrome）⇒ 拒绝绑定。"""
    host = _perceive(attest=_v("real"))
    with pytest.raises(RuntimeError, match="attestation refused"):
        host.probe_page_target()


def test_allow_real_policy_binds_real_chrome():
    host = _perceive(policy=BindingPolicy.permit_real("digest"), attest=_v("real"))
    info = host.probe_page_target()
    assert info["target_id"] == "t-1"


def test_shadow_mode_binds_real_chrome_without_refusal():
    host = _perceive(policy=BindingPolicy.deny_real(mode="shadow"), attest=_v("real"))
    info = host.probe_page_target()
    assert info["target_id"] == "t-1"


def test_dedicated_verdict_binds_under_default_policy():
    host = _perceive(attest=_v("dedicated"))
    assert host.probe_page_target()["target_id"] == "t-1"


def test_coordinator_attestation_verdict_mismatch_refused():
    """两 host 同一实例身份但 attestation verdict 不一致 ⇒ 拒绝（mutation 通道校验）。"""
    coord = BrowserChannelBindingCoordinator()
    perceive = _perceive(coord=coord, attest=_v("dedicated", sha="d" * 64))
    perceive.probe_page_target()
    assert coord.binding.verdict == "dedicated"
    # actuator 同一实例身份（uuid-1/t-1）但读到不同 argv/verdict
    actuator = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="t-1",
        http_get_json=lambda url: [{
            "id": "t-1", "type": "page", "url": "about:blank",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/t-1",
        }],
        http_get_version_dict=lambda url: {
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/uuid-1"},
        ws_connect=lambda url: _FakeWs(),
        binding_coordinator=coord,
        binding_policy=BindingPolicy.permit_real("digest"),
        attest_fn=lambda url: _v("real", sha="e" * 64),
    )
    with pytest.raises(RuntimeError, match="attestation"):
        actuator.dispatch(verb="scroll", physical_target="dom:1", args={"delta_pages": 1})


# ── 5. 机制 fail-closed（真 lsof） ──────────────────────────────────────


def test_attest_dead_port_fail_closed_real():
    verdict = attest_port(39099, TREES)  # 无监听
    assert verdict.verdict == "real"
    assert "无监听" in verdict.detail


def test_attest_debug_url_carries_paths_semantics():
    v = attest_debug_url("http://127.0.0.1:39099", "none")
    assert v.verdict == "real"
    v2 = attest_debug_url("http://127.0.0.1:39099", "bad/relative")
    assert v2.verdict == "real" and "PATHS" in v2.detail


# ── 6. 原生 NUL 分隔 argv 源（S4 空格截断修复，2026-10-06） ────────────────

CHROME_ARGV_SPACES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "--user-data-dir=/tmp/attest dir with space",
    "about:blank",
]


def test_parse_proc_cmdline_preserves_spaces():
    data = b"\x00".join(a.encode() for a in CHROME_ARGV_SPACES) + b"\x00"
    assert attestation_mod._parse_proc_cmdline(data) == CHROME_ARGV_SPACES
    with pytest.raises(ValueError):
        attestation_mod._parse_proc_cmdline(b"")  # 内核线程/空
    with pytest.raises(ValueError):
        attestation_mod._parse_proc_cmdline(b"\x00\x00")


def test_parse_procargs2_preserves_spaces():
    """构造真实布局：[argc:int32][exec path\\0][NUL padding][argv 各\\0]。"""
    args = [CHROME_ARGV_SPACES[0], "--user-data-dir", "/tmp/dir  with  spaces", "about:blank"]
    buf = len(args).to_bytes(4, sys.byteorder)
    buf += args[0].encode() + b"\x00"  # exec path（其后 argv[0] 会重复出现）
    while len(buf) % 8:  # 8 字节对齐 padding，模拟内核布局
        buf += b"\x00"
    for a in args:  # 全部 argc 个 argv 串（含 argv[0]）
        buf += a.encode() + b"\x00"
    assert attestation_mod._parse_procargs2(buf) == args
    with pytest.raises(ValueError):
        attestation_mod._parse_procargs2(b"\x01\x00")  # 过短
    with pytest.raises(ValueError):
        attestation_mod._parse_procargs2((0).to_bytes(4, sys.byteorder) + b"x\x00")  # argc=0
    with pytest.raises(ValueError):
        attestation_mod._parse_procargs2(b"\xff" * 4 + b"chrome\x00chrome\x00")  # argc 越界


def test_pid_argv_prefers_native(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(
        attestation_mod, "_macos_procargs2_argv",
        lambda pid: list(CHROME_ARGV_SPACES),
    )
    called = {"ps": 0}

    def _ps(pid):
        called["ps"] += 1
        raise AssertionError("不应回落 ps")

    monkeypatch.setattr(attestation_mod, "_ps_argv", _ps)
    assert attestation_mod._pid_argv("123") == CHROME_ARGV_SPACES
    assert called["ps"] == 0


def test_pid_argv_falls_back_to_ps_on_native_failure(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)

    def _boom(pid):
        raise OSError(1, "denied")

    monkeypatch.setattr(attestation_mod, "_macos_procargs2_argv", _boom)
    monkeypatch.setattr(attestation_mod, "_ps_argv", lambda pid: ["chrome", "--user-data-dir=/tmp/p"])
    assert attestation_mod._pid_argv("123") == ["chrome", "--user-data-dir=/tmp/p"]


def test_native_spaces_argv_classifies_dedicated(tmp_path, monkeypatch):
    """端到端（argv 采集层）：含空格 profile 的完整 argv ⇒ verdict=dedicated 而非误 real。"""
    profile = tmp_path / "dir with space"
    profile.mkdir()
    argv = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            f"--user-data-dir={profile}", "about:blank"]
    value = extract_user_data_dir_value(argv)
    assert value == str(profile)
    verdict, _ = classify_user_data_dir(value, TREES)
    assert verdict == "dedicated"
    # 反例：默认树内含空格子目录 ⇒ 仍 real（修复不得放过真默认 profile）
    sub = TREES[0] / "Profile 1"
    verdict2, _ = classify_user_data_dir(str(sub), TREES)
    assert verdict2 == "real"


@pytest.mark.skipif(sys.platform != "darwin", reason="仅 macOS 有 KERN_PROCARGS2")
def test_macos_procargs2_real_process():
    """真进程冒烟：对自己（pytest 进程）读 procargs2，argv[0] 含 python 可执行路径。"""
    argv = attestation_mod._macos_procargs2_argv(str(os.getpid()))
    assert argv, "procargs2 应解析出非空 argv"
    assert any("python" in a.lower() for a in argv[:1] + argv)
