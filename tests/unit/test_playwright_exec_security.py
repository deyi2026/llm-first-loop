"""playwright_exec 安全门控对抗性测试（2026-08-16 DSH 独立审查 payload 清单）.

覆盖 DSH 审查发现的 3 条真实绕过路径（修复后全部应拦截/隔离）:
- 发现 1: AST 门控动态导入绕过（14 种形态 → 全部 blocked）
- 发现 2: 模型代码共享命名空间摸裸 API（→ 命名空间隔离后 NameError）
- 发现 3: URL 白名单正则逃逸（userinfo@host/域后缀 → host 精确校验拦截）
"""

from llm_loop.introspection.tools_playwright import _validate_url
from llm_loop.introspection.tools_playwright_exec import _PREAMBLE, _scan_code

# ── 发现 1: AST 门控（14 种动态导入形态，全部应拦截）──
BLOCKED_PAYLOADS = [
    "import playwright",
    "from playwright.sync_api import sync_playwright",
    "import playwright as pw",
    "__import__('playwright')",
    "__import__('playwright.sync_api', fromlist=['x'])",
    "__import__('play' + 'wright')",
    "import importlib; importlib.import_module('playwright.sync_api')",
    "from importlib import import_module; import_module('playwright')",
    "getattr(importlib, 'import_module')('playwright')",
    "exec(\"import playwright\")",
    "eval(\"__import__('playwright')\")",
    "compile(\"import playwright\", '<x>', 'exec')",
    "import sys; m = sys.modules['playwright.sync_api']",
    "import sys; m = sys.modules.get('playwright')",
]


def test_ast_gate_blocks_all_dynamic_imports():
    """14 种动态导入形态全部拦截（含 DSH 实弹验证的绕过形态）."""
    for payload in BLOCKED_PAYLOADS:
        ok, err = _scan_code(payload)
        assert not ok, f"未拦截: {payload!r}"


def test_ast_gate_allows_normal_helper_code():
    """正常 helper 用法不受影响."""
    ok, _ = _scan_code(
        "goto('https://a.feishu.cn/x')\n"
        "click('#btn')\n"
        "print(axtree_text())"
    )
    assert ok


# ── 发现 2: 命名空间隔离（模型代码不可见内部对象）──
def test_preamble_isolates_model_namespace():
    """preamble 必须以 _run_model 隔离执行模型代码（内部对象不可见）."""
    assert "_run_model(__MODEL_CODE__)" in _PREAMBLE
    assert "__builtins__" in _PREAMBLE
    # helper 仍闭包引用内部对象（功能不受影响）
    assert "def goto(url):" in _PREAMBLE
    assert "_HELPERS" in _PREAMBLE


# ── 发现 3: URL 沙箱（host 精确校验，绕过 payload 全部拦截）──
BLOCKED_URLS = [
    "https://a.feishu.cn@example.com/",        # userinfo@host
    "https://a.feishu.cn.evil.com/",           # 域后缀
    "https://a.feishu.cn:443@evil.com/steal",  # userinfo+端口混淆
    "https://feishu.cn.evil.com/",             # 裸域+后缀
    "http://0x7f000001/",                      # 十六进制 IP
    "http://0x7f.0.0.1/",                      # 混合 IP 变体
    "http://127.1/",                           # 短 IP
    "http://2130706433/",                      # 十进制 IP
    "http://[::1]/",                           # IPv6
    "http://localhost.evil.com/",              # localhost 域后缀
    "http://localhost@evil.com/",              # localhost userinfo
    "http://127.0.0.1.evil.com/",              # IP 域后缀
    "file:///etc/passwd",                      # 非 http(s) 协议
    "https://evil.com/",                       # 普通外部域
]

ALLOWED_URLS = [
    "https://a.feishu.cn/x",
    "https://feishu.cn/",                       # 裸域（修复 false-negative）
    "https://FEISHU.CN/",                       # 大写（hostname 已 lower，大小写不敏感——修复 false-negative）
    "http://localhost:8902/",
    "http://localhost/",
    "http://127.0.0.1:8902/api/v1/health",
]


def test_url_sandbox_blocks_evasion_payloads():
    for url in BLOCKED_URLS:
        ok, _ = _validate_url(url)
        assert not ok, f"未拦截: {url!r}"


def test_url_sandbox_allows_whitelist():
    for url in ALLOWED_URLS:
        ok, err = _validate_url(url)
        assert ok, f"误拦: {url!r} -> {err}"


# ── 2026-08-16 DSH 复核 005 建议 a+c：env 剥离 + cwd 限定 ──
def test_child_env_strips_sensitive_keys(monkeypatch):
    """敏感键（KEY/SECRET/TOKEN/PASSWORD 等）被剥离，普通键保留."""
    from llm_loop.introspection.tools_playwright_exec import _child_env

    monkeypatch.setenv("OPENAI_API_KEY", "sk-xxx")
    monkeypatch.setenv("FEISHU_APP_SECRET", "sec-xxx")
    monkeypatch.setenv("MY_TOKEN", "tok")
    monkeypatch.setenv("DB_PASSWORD", "pw")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/Users/test")
    env = _child_env()
    assert "OPENAI_API_KEY" not in env
    assert "FEISHU_APP_SECRET" not in env
    assert "MY_TOKEN" not in env
    assert "DB_PASSWORD" not in env
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/Users/test"


def test_child_workdir_limits_to_session(tmp_path, monkeypatch):
    """cwd 限定 data/e2e/<session>/ 且目录已建."""
    from llm_loop.introspection.tools_playwright_exec import _child_workdir

    monkeypatch.chdir(tmp_path)
    wd = _child_workdir("secreview-test")
    assert wd == (tmp_path / "data" / "e2e" / "secreview-test").resolve()
    assert wd.exists()
