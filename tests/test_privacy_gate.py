"""推送隐私闸回归测试（规则5 / --range 逐提交 / --commit / pre-push 集成）。
背景：2026-10-29 知识卡携内网 IP+用户名推上公开仓；修复审查发现 --range 净 diff 会漏掉
"中间提交引入后被还原"的泄露（P1），本测试固化该行为契约。"""
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(REPO, "scripts", "git_security_scan.sh")
HOOK = os.path.join(REPO, ".githooks", "pre-push")


def run_scan(repo, *args, env_user=None):
    env = dict(os.environ)
    if env_user is not None:
        env["USER"] = env_user
    return subprocess.run(["bash", SCAN, *args], cwd=repo, env=env,
                          capture_output=True, timeout=120,
                          encoding="utf-8", errors="replace")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    def git(*a):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (r / "base.txt").write_text("base\\n")
    git("add", ".")
    git("commit", "-q", "-m", "base", "--no-verify")
    return r


def commit_file(r, name, content, msg):
    (r / name).write_text(content)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", msg, "--no-verify"], check=True, capture_output=True)


def rev(r, ref="HEAD"):
    return subprocess.run(["git", "-C", str(r), "rev-parse", ref],
                          check=True, capture_output=True, text=True).stdout.strip()


def test_staged_blocks_private_ip(repo):
    (repo / "a.md").write_text("server 192.168.7.99\\n")
    subprocess.run(["git", "-C", str(repo), "add", "a.md"], check=True)
    assert run_scan(repo, "--staged").returncode == 1


def test_staged_blocks_user_at_host(repo):
    (repo / "b.md").write_text("ssh testuser@203.0.113.7 ok\\n")
    subprocess.run(["git", "-C", str(repo), "add", "b.md"], check=True)
    assert run_scan(repo, "--staged", env_user="testuser").returncode == 1


def test_staged_blocks_hostname_prefix(repo):
    (repo / "c.md").write_text("host testuser-pc up\\n")
    subprocess.run(["git", "-C", str(repo), "add", "c.md"], check=True)
    assert run_scan(repo, "--staged", env_user="testuser").returncode == 1


def test_staged_generic_ci_user_skips_identity_patterns(repo):
    """通用 CI 账户（runner 等）不是私有身份：user@/user-前缀动态模式跳过，正常英文不得误拦（2026-10-29 CI 红根因）。"""
    (repo / "ci.md").write_text("CI 门禁：runner-proof 纪律；卡名 runner-silence-is-invocation-error 引用")
    subprocess.run(["git", "-C", str(repo), "add", "ci.md"], check=True)
    assert run_scan(repo, "--staged", env_user="runner").returncode == 0


def test_staged_generic_ci_user_still_blocks_private_ip(repo):
    """通用账户跳过仅限动态身份模式：私网 IPv4 静态规则不受影响，必须继续拦。"""
    (repo / "ci_ip.md").write_text("edge-bind 192.168.3.9")
    subprocess.run(["git", "-C", str(repo), "add", "ci_ip.md"], check=True)
    assert run_scan(repo, "--staged", env_user="runner").returncode == 1


def test_staged_blocks_current_user_home_path(repo):
    """规则5 主目录路径动态模式：裸用户名形态 /Users/<user>/ 必须拦（review P2-1，规则3 豁免防不住）。"""
    (repo / "h.md").write_text("tail -5 /Users/testuser/Project/x.log")
    subprocess.run(["git", "-C", str(repo), "add", "h.md"], check=True)
    assert run_scan(repo, "--staged", env_user="testuser").returncode == 1


def test_staged_clean_passes(repo):
    (repo / "d.md").write_text("innocuous\\n")
    subprocess.run(["git", "-C", str(repo), "add", "d.md"], check=True)
    assert run_scan(repo, "--staged").returncode == 0


def test_range_catches_intermediate_commit_leak(repo):
    """P1 回归：中间提交引入隐私、后续提交删除——端点净 diff 看不到（D 被过滤）但历史仍在，必须拦。"""
    base = rev(repo)
    commit_file(repo, "leak.md", "ip 10.55.66.77\\n", "leak")
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "leak.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "purge", "--no-verify"], check=True, capture_output=True)
    head = rev(repo)
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=ACM", base, head],
                         capture_output=True, text=True)
    assert "leak.md" not in out.stdout  # 前置：ACM 净 diff 确实看不到（否则用例失效）
    assert run_scan(repo, "--range", base, head).returncode == 1  # 逐提交必须拦


def test_range_clean_passes(repo):
    base = rev(repo)
    commit_file(repo, "ok.md", "fine\\n", "ok")
    head = rev(repo)
    assert run_scan(repo, "--range", base, head).returncode == 0


def test_commit_mode_scans_full_history(repo):
    """--commit=SHA 扫该提交可达的完整历史（首推语义）：中间泄露必须拦。"""
    commit_file(repo, "leak.md", "server 172.16.5.5\\n", "dirty")
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "leak.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "purge", "--no-verify"], check=True, capture_output=True)
    sha2 = rev(repo)
    assert run_scan(repo, "--commit", sha2).returncode == 1  # tip 干净但历史含泄露——必须拦


def test_commit_mode_clean_history_passes(repo):
    commit_file(repo, "ok.txt", "fine\\n", "ok")
    sha = rev(repo)
    assert run_scan(repo, "--commit", sha).returncode == 0


def test_commit_mode_fail_closed_on_bad_ref(repo):
    assert run_scan(repo, "--commit", "deadbeef").returncode == 1  # 不可解析 ref 拒绝而非静默通过


def test_ere_escape_dynamic_user(repo):
    """动态用户名含 ERE 元字符时必须按字面匹配（转义回归）。"""
    (repo / "e.md").write_text("run a.b*c@203.0.113.9 now\\n")
    subprocess.run(["git", "-C", str(repo), "add", "e.md"], check=True)
    assert run_scan(repo, "--staged", env_user="a.b*c").returncode == 1


def test_allowlist_exact_and_suffix_passes(repo):
    """豁免=精确/目录后缀锚定：docs/.env.example 命中（*/.env.example），非子串。"""
    d = repo / "docs"
    d.mkdir()
    f = d / ".env.example"
    f.write_text("ROUTER=192.168.0.1\\n")
    subprocess.run(["git", "-C", str(repo), "add", str(f)], check=True)
    assert run_scan(repo, "--staged").returncode == 0


def test_allowlist_no_substring_bypass(repo):
    """登记项不被子串旁路：vendor/.../tests/test_privacy_gate.py.bak 必须照常拦截。"""
    d = repo / "vendor" / "x"
    d.mkdir(parents=True)
    f = d / "tests.test_privacy_gate.py.bak"
    f.write_text("ip 10.77.77.77\\n")
    subprocess.run(["git", "-C", str(repo), "add", str(f)], check=True)
    assert run_scan(repo, "--staged").returncode == 1


def test_pre_push_hook_blocks_dirty_range(repo, tmp_path):
    base = rev(repo)
    commit_file(repo, "leak.md", "ssh yo@203.0.113.8\\n", "dirty")
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "leak.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "purge", "--no-verify"], check=True, capture_output=True)
    head = rev(repo)
    refs = "refs/heads/main " + head + " refs/heads/main " + base + "\n"
    env = dict(os.environ)
    env["USER"] = "yo"
    out = subprocess.run(["bash", HOOK], cwd=repo, input=refs, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 1  # 钩子 fail-closed：脏 range 必须拦住推送


def test_rule5_blocks_username_path_in_rule3_exempt_dir(repo):
    """P1 回归（2026-10-30 push 闸 REVISE P1-1）：规则3 对 experiences/ 粒度豁免，
    规则5 必须独立拦下裸用户名路径形态——且在通用 CI 账户下同样拦（静态模式）。

    审查指控：旧实现只有**动态** /Users/<当前用户>/ 模式，CI 用通用账户（runner）
    时该模式被跳过 → 知识档案里的用户名路径在 CI 上直接放行（闸形同虚设）。
    """
    d = repo / "experiences"
    d.mkdir(parents=True, exist_ok=True)
    (d / "e.md").write_text("tail -5 /Users/someoneelse/Project/x.log")
    subprocess.run(["git", "-C", str(repo), "add", "experiences/e.md"], check=True)
    assert run_scan(repo, "--staged", env_user="runner").returncode == 1


def test_rule5_allows_masked_username_path(repo):
    """脱敏形态 /Users/<user>/ 不得误报（'<' 不在用户名字符类内）。

    这是本次改造的可用性底线：闸变严不能把仓库自有文档约定（docs/ 与知识卡统一用
    /Users/<user>/）判成违规。
    """
    (repo / "m.md").write_text("tail -5 /Users/<user>/Project/x.log")
    subprocess.run(["git", "-C", str(repo), "add", "m.md"], check=True)
    assert run_scan(repo, "--staged").returncode == 0


def test_rule5_allows_ellipsis_path_placeholder(repo):
    """省略号路径示例（/Users/.../）不是用户名，不得误报。

    复核发现：静态模式原为 /Users/[A-Za-z0-9_.-]+/，字符类含 '.' → 省略号形态
    （src/llm_loop/llm/providers.py 的模型路径示例）被当成用户名命中。
    修复：首字符强制字母数字。
    """
    (repo / "e.py").write_text('# 如 "/Users/.../.lmstudio/models/org/X"\n')
    subprocess.run(["git", "-C", str(repo), "add", "e.py"], check=True)
    assert run_scan(repo, "--staged").returncode == 0


def test_rule5_allows_macos_shared_public_dir(repo):
    """P2-2 回归：/Users/Shared/ 是 macOS 系统公共目录（非家目录用户名）→ 不得误报。

    独立审查 2026-10-30 P2-2：静态模式 /Users/<name>/ 会把合法系统路径当用户名命中，
    未来文档一旦提及即误报。修复：命中用户名若全在 _SAFE_HOME_DIRS 内则不算身份暴露。
    """
    (repo / "s.md").write_text("ls /Users/Shared/Public\n")
    subprocess.run(["git", "-C", str(repo), "add", "s.md"], check=True)
    assert run_scan(repo, "--staged").returncode == 0


def test_rule5_still_blocks_real_user_beside_shared_dir(repo):
    """安全目录例外不得放宽成整体放行：同文件出现真实用户名形态仍必须拦。"""
    (repo / "s2.md").write_text("ls /Users/Shared/Public /Users/someoneelse/x\n")
    subprocess.run(["git", "-C", str(repo), "add", "s2.md"], check=True)
    assert run_scan(repo, "--staged").returncode == 1


def test_gate_own_test_file_is_broadly_exempt():
    """P2-3 回归：本文件含 /Users/<样例用户名>/ 字面量（规则5 用例样本）。

    规则5 不继承 _PATH_ONLY/_ABS_PATH_ONLY/_PRIVACY_ONLY 粒度豁免 → 本文件必须由
    **全规则**豁免（_ALLOWLIST）覆盖，否则闸会自阻塞（自己的测试样本把自己拦下）。
    """
    with open(SCAN, encoding="utf-8") as fh:
        script = fh.read()
    m = re.search(r"_ALLOWLIST=\((.*?)\n\)", script, re.S)
    assert m, "未找到 _ALLOWLIST 定义"
    entries = re.findall(r"'([^']+)'", m.group(1))
    assert "tests/test_privacy_gate.py" in entries
    # 豁免是承重的：本文件确实含规则5 会命中的裸用户名形态
    with open(__file__, encoding="utf-8") as fh:
        assert "/Users/someoneelse/" in fh.read()


def test_range_fails_closed_on_unreadable_history_blob(repo):
    """P2-1 回归：历史 blob 读取失败必须 fail-closed，不得静默跳过。

    静默跳过 = 该 blob 的全部内容规则失效；空扫描会"假通过"且不留痕迹。
    独立审查 2026-10-30 P2-1：原实现 `|| continue`（远端已修的 fail-closed 被回退）。
    """
    base = rev(repo)
    commit_file(repo, "blob.md", "hello\n", "add")
    head = rev(repo)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD:blob.md"],
                         check=True, capture_output=True, text=True).stdout.strip()
    obj = repo / ".git" / "objects" / sha[:2] / sha[2:]
    if not obj.exists():
        pytest.skip("blob 已被打包，无法构造不可读对象")
    obj.unlink()
    out = run_scan(repo, "--range", base, head)
    assert out.returncode == 1  # fail-closed：拒绝而非静默跳过
    assert "不可读" in out.stderr or "fail-closed" in out.stderr


# ── 规则3「URL 内嵌家目录」前缀收窄（2026-11-02 误报修复）──────────────────────
# 收窄：前缀 [^[:space:]]* → [^/[:space:]]+，即 /home/ 只能落在 URL 的 path 起始处。
# 动机：公开文档站的多段路径（主机/help/home/<段>/<段>，home 只是文档路径里的一节）
# 原被当作家目录泄漏——实测假阳性，且仓库 tracked 内容里没有 help/home/ 形态的文件，
# 只能靠直接喂样本复现，故此处用样本锁住双向。
#
# 下列 URL 均为虚构主机/用户名，仅作被扫样本；本文件已在 _ALLOWLIST（全规则豁免），
# 故这些字面量不会让闸自阻塞（契约见上方 test_gate_own_test_file_is_broadly_exempt）。
# 样本刻意不含裸家目录形态（/home/ 紧贴非字母数字边界），确保命中/未命中只可能由
# 本 URL 规则决定，不会被规则3 的前导边界模式或规则5 的当前用户模式抢答。
_URL_HOME_MUST_HIT = [
    "https://host/home/alice/panel",   # 基线形态：主机 + 家目录段 + 子段
    "https://host:8443/home/bob/x",    # 带端口：host 段含 ':' 仍须算 path 起始
    "http://u:p@host/home/carol/p",    # userinfo 前缀：仍须命中
]
_URL_HOME_MUST_MISS = "https://docs.example.com/help/home/index/2"  # 公开文档站多段路径
_URL_PAT_PREFIX = "https?://"  # 规则3 块内仅 URL 模式以此开头（其余为路径模式）


def _url_home_pattern() -> str:
    """从脚本规则3 块中抽取 URL 家目录模式的字面值（收窄后应只有一条）。"""
    with open(SCAN, encoding="utf-8") as fh:
        script = fh.read()
    m = re.search(r"BLOCK_ABS_PATH_PATTERNS=\((.*?)\n\)", script, re.S)
    assert m, "未找到 BLOCK_ABS_PATH_PATTERNS 定义"
    hits = [p for p in re.findall(r"'([^']+)'", m.group(1))
            if p.startswith(_URL_PAT_PREFIX)]
    assert len(hits) == 1, f"URL 家目录模式应恰有一条，实际 {hits}"
    return hits[0]


def test_url_home_pattern_is_path_anchored():
    """结构性锁定：模式必须把 host 段限制为不含 '/'（/home/ 只在 path 起始）。

    收窄前的 [^[:space:]]* 前缀会跨过 '/'，让任意深度的 /home/ 都算家目录泄漏。
    """
    pat = _url_home_pattern()
    assert pat == "https?://[^/[:space:]]+/home/[A-Za-z0-9_]+/[A-Za-z0-9_.-]+"
    assert "[^[:space:]]*/home/" not in pat  # 旧前缀不得回归


def test_url_home_pattern_two_way_grep():
    """用脚本里的**实际模式**喂样本（grep -E 与脚本同引擎）：双向锁定。

    必须命中：真家目录形态（含端口/userinfo）——收窄不得放宽防护面。
    必须不命中：公开文档站多段路径——本次修复的目标误报。
    """
    pat = _url_home_pattern()

    def hits(u: str) -> bool:
        return subprocess.run(["grep", "-Eq", pat], input=u + "\n",
                              capture_output=True, text=True, timeout=30).returncode == 0

    for url in _URL_HOME_MUST_HIT:
        assert hits(url), f"收窄过度：真家目录形态漏拦 {url}"
    assert not hits(_URL_HOME_MUST_MISS), "误报未消除：公开文档站多段路径仍被拦"


@pytest.mark.parametrize("url", _URL_HOME_MUST_HIT)
def test_scan_blocks_url_embedded_home_leak(repo, url):
    """整脚本行为：URL 内嵌家目录形态必须仍被规则3 拦下（exit 1）。

    env_user 固定为通用 CI 账户，隔离规则5 的动态身份模式，让命中只可能来自规则3。
    """
    (repo / "leak.md").write_text(f"open {url}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "leak.md"], check=True, capture_output=True)
    out = run_scan(repo, "--staged", env_user="runner")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "本地绝对路径匹配" in out.stdout  # 出自规则3，不是别的规则抢答


def test_scan_passes_public_docs_multisegment_path(repo):
    """整脚本行为：公开文档站多段路径（home 只是文档路径一节）不得阻塞（exit 0）。

    这是本次收窄的可用性目标：闸变准不能把公开文档链接判成家目录泄漏。
    """
    (repo / "docs_link.md").write_text(f"see {_URL_HOME_MUST_MISS}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "docs_link.md"], check=True, capture_output=True)
    out = run_scan(repo, "--staged", env_user="runner")
    assert out.returncode == 0, out.stdout + out.stderr

