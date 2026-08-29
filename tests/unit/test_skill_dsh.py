"""tools_skill_dsh 单测（SDD-20260829 T5）: 全离线（monkeypatch _fetch），不触网."""

from __future__ import annotations

import json

import pytest

from llm_loop.introspection import tools_skill_dsh as dsh
from llm_loop.introspection.tools_skill_files import run_skill_list, run_skill_load

FAKE_README = """# Awesome
<!-- BEGIN TOC -->
- [Plugins](#plugins)
<!-- END TOC -->
## Plugins
### UI Enhancements
- [alice/ui-pro](https://github.com/alice/ui-pro) - Best UI plugin with themes.
- [bob/theme-pack](https://github.com/bob/theme-pack) - Themes collection.

### Memory
- [carol/mem-x](https://github.com/carol/mem-x) - Memory plugin.

## Contributing
- [awesome-dsh-plugin/awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) - This list itself.
"""


class FakeHost:
    def __init__(self, audit_dir=None, skills_dir=None):
        self.audit_dir = audit_dir
        self.skills_dir = skills_dir


def test_parse_awesome_synthetic():
    plugins = dsh.parse_awesome(FAKE_README)
    repos = [p["repo"] for p in plugins]
    assert repos == ["alice/ui-pro", "bob/theme-pack", "carol/mem-x"]
    by = {p["repo"]: p for p in plugins}
    assert by["alice/ui-pro"]["category"] == "UI Enhancements"
    assert by["carol/mem-x"]["category"] == "Memory"
    assert "UI plugin" in by["alice/ui-pro"]["desc"]


def test_fetch_whitelist_rejects_foreign_domain():
    with pytest.raises(PermissionError):
        dsh._fetch("https://evil.example.com/payload.js")


def test_index_cache_ttl(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dsh, "_fetch", lambda url: calls.append(url) or FAKE_README)
    host = FakeHost(audit_dir=tmp_path)
    p1, s1 = dsh._load_index(host)
    assert p1 is not None and len(p1) == 3 and len(calls) == 1
    p2, _ = dsh._load_index(host)
    assert len(calls) == 1  # TTL 内走缓存
    cache = tmp_path / "dsh_index.json"
    data = json.loads(cache.read_text())
    data["fetched_at"] -= dsh.INDEX_TTL_S + 1  # 人工过期
    cache.write_text(json.dumps(data))
    p3, _ = dsh._load_index(host)
    assert len(calls) == 2  # 过期重拉
    assert [p["repo"] for p in p3] == [p["repo"] for p in p1]


def test_index_without_auditdir(tmp_path, monkeypatch):
    n = []
    monkeypatch.setattr(dsh, "_fetch", lambda url: n.append(1) or FAKE_README)
    p, status = dsh._load_index(FakeHost(audit_dir=None))
    assert p is not None and len(p) == 3 and len(n) == 1  # 免缓存直拉仍可用


def test_skill_list_appends_dsh_section(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh, "_fetch", lambda url: FAKE_README)
    res = run_skill_list(FakeHost(audit_dir=tmp_path, skills_dir=None), {})
    assert "[DSH 插件索引]" in res.content and "3 插件" in res.content


def test_skill_list_zero_regression_on_adapter_crash(tmp_path, monkeypatch):
    def boom(url):
        raise OSError("network down")

    monkeypatch.setattr(dsh, "_fetch", boom)
    res = run_skill_list(FakeHost(audit_dir=tmp_path, skills_dir=None), {})
    assert res.content.startswith("[技能清单]")  # 本地段不受影响


def test_skill_load_dsh_route_card(tmp_path, monkeypatch):
    def routing_fetch(url):
        if "README.md" in url and "alice/ui-pro" in url:
            return "# UI Pro\nA great plugin."
        return FAKE_README

    monkeypatch.setattr(dsh, "_fetch", routing_fetch)
    res = run_skill_load(FakeHost(audit_dir=tmp_path), {"name": "dsh:alice/ui-pro"})
    assert res.status.value == "success"
    assert "[DSH 插件卡] alice/ui-pro" in res.content
    assert "UI Enhancements" in res.content and "dsh_task 桥接" in res.content
    assert "A great plugin." in res.content


def test_skill_load_dsh_not_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh, "_fetch", lambda url: FAKE_README)
    res = run_skill_load(FakeHost(audit_dir=tmp_path), {"name": "dsh:zz/none"})
    assert res.status.value == "failure" and "未收录" in res.content


def test_skill_load_dsh_bad_format(tmp_path):
    res = run_skill_load(FakeHost(audit_dir=tmp_path), {"name": "dsh:bad name"})
    assert res.status.value == "failure" and "参数错误" in res.content


def test_skill_load_dsh_readme_fail_still_card(tmp_path, monkeypatch):
    def routing_fetch(url):
        if "alice/ui-pro" in url and url.endswith("README.md"):
            raise OSError("404")
        return FAKE_README

    monkeypatch.setattr(dsh, "_fetch", routing_fetch)
    res = run_skill_load(FakeHost(audit_dir=tmp_path), {"name": "dsh:alice/ui-pro"})
    assert res.status.value == "success" and "README 拉取失败" in res.content
