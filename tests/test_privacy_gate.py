"""推送隐私闸回归测试（规则5 / --range 逐提交 / --commit / pre-push 集成）。
背景：2026-10-29 知识卡携内网 IP+用户名推上公开仓；修复审查发现 --range 净 diff 会漏掉
"中间提交引入后被还原"的泄露（P1），本测试固化该行为契约。"""
import os
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
    env = dict(os.environ); env["USER"] = "yo"
    out = subprocess.run(["bash", HOOK], cwd=repo, input=refs, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 1  # 钩子 fail-closed：脏 range 必须拦住推送
