"""extensions/formats 单测（DESIGN-20261009 P1-A: T15/T16/T17 + §10.2 上限）."""

import json
from pathlib import Path

from llm_loop.extensions.formats import (
    MAX_COMPONENTS,
    PACKAGE_PARTIAL,
    PACKAGE_READY,
    PACKAGE_UNAVAILABLE,
    STATUS_INVALID,
    STATUS_NEEDS_CONFIG,
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
    parse_plugin_package,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "std_plugin_demo"


def _mk_pkg(tmp_path: Path, manifest: dict | str, *, skills=None, mcp=None):
    root = tmp_path / "pkg"
    root.mkdir(parents=True)
    if isinstance(manifest, str):
        (root / "plugin.json").write_text(manifest)
    else:
        (root / "plugin.json").write_text(json.dumps(manifest))
    for name, text in (skills or {}).items():
        d = root / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(text)
    if mcp is not None:
        (root / "mcp.json").write_text(
            mcp if isinstance(mcp, str) else json.dumps(mcp)
        )
    return root


GOOD_MANIFEST = {
    "name": "demo",
    "schema_version": "1.0.0",
    "version": "0.1.0",
}
GOOD_SKILL = "---\nname: s1\ndescription: d1\n---\n# s1\n正文\n"


class TestManifestValidity:
    def test_fixture_package_ready(self):
        r = parse_plugin_package(FIXTURE)
        assert r.plugin_name == "demo-plugin"
        assert r.overall == PACKAGE_READY
        assert [s.status for s in r.skills] == [STATUS_SUPPORTED] * 2
        assert [s.status for s in r.servers] == [STATUS_SUPPORTED]

    def test_invalid_json_manifest_unavailable(self, tmp_path):
        root = _mk_pkg(tmp_path, "{not json")
        r = parse_plugin_package(root)
        assert r.overall == PACKAGE_UNAVAILABLE
        assert any("invalid manifest" in w for w in r.warnings)

    def test_manifest_not_object_unavailable(self, tmp_path):
        root = _mk_pkg(tmp_path, '["list"]')
        assert parse_plugin_package(root).overall == PACKAGE_UNAVAILABLE

    def test_manifest_missing_name_unavailable(self, tmp_path):
        root = _mk_pkg(tmp_path, {"schema_version": "1.0.0"})
        r = parse_plugin_package(root)
        assert r.overall == PACKAGE_UNAVAILABLE
        assert any("missing required field: name" in w for w in r.warnings)

    def test_root_missing_unavailable(self, tmp_path):
        r = parse_plugin_package(tmp_path / "nope")
        assert r.overall == PACKAGE_UNAVAILABLE


class TestT15NonFatalFields:
    def test_unknown_top_level_fields_warn_not_fail(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            {**GOOD_MANIFEST, "future_field": 1, "another": "x"},
            skills={"s1": GOOD_SKILL},
        )
        r = parse_plugin_package(root)
        assert r.overall == PACKAGE_READY
        assert any("unknown manifest fields" in w for w in r.warnings)

    def test_extensions_non_object_warn_not_fail(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            {**GOOD_MANIFEST, "extensions": "not-an-object"},
            skills={"s1": GOOD_SKILL},
        )
        r = parse_plugin_package(root)
        assert r.overall == PACKAGE_READY
        assert any("extensions is not an object" in w for w in r.warnings)

    def test_missing_schema_version_warns(self, tmp_path):
        root = _mk_pkg(
            tmp_path, {"name": "demo"}, skills={"s1": GOOD_SKILL}
        )
        r = parse_plugin_package(root)
        assert r.overall == PACKAGE_READY
        assert any("schema_version" in w for w in r.warnings)


class TestT16ComponentIsolation:
    def test_bad_skill_isolated_good_kept(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            skills={"good": GOOD_SKILL, "bad": "not frontmatter at all\n"},
        )
        r = parse_plugin_package(root)
        by_dir = {s.rel_path.split("/")[1]: s for s in r.skills}
        assert by_dir["good"].status == STATUS_SUPPORTED
        assert by_dir["bad"].status == STATUS_INVALID

    def test_skill_missing_name_invalid(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            skills={"x": "---\ndescription: no name\n---\nbody\n"},
        )
        r = parse_plugin_package(root)
        assert r.skills[0].status == STATUS_INVALID

    def test_missing_skill_md_invalid(self, tmp_path):
        root = _mk_pkg(tmp_path, GOOD_MANIFEST, skills={})
        (root / "skills" / "empty").mkdir(parents=True)
        r = parse_plugin_package(root)
        assert r.skills[0].status == STATUS_INVALID
        assert "missing SKILL.md" in r.skills[0].reason

    def test_mcp_json_invalid_warns_skills_kept(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            skills={"s1": GOOD_SKILL},
            mcp="{broken",
        )
        r = parse_plugin_package(root)
        assert r.overall == PACKAGE_PARTIAL  # 技能可用、server 缺失
        assert r.servers == ()
        assert any("mcp.json" in w for w in r.warnings)

    def test_unknown_server_type_unsupported_isolated(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            skills={"s1": GOOD_SKILL},
            mcp={"mcpServers": {
                "weird": {"type": "websocket"},
                "ok": {"type": "stdio", "command": "echo"},
            }},
        )
        r = parse_plugin_package(root)
        by_name = {s.name: s for s in r.servers}
        assert by_name["weird"].status == STATUS_UNSUPPORTED
        assert by_name["ok"].status == STATUS_SUPPORTED
        assert r.overall == PACKAGE_PARTIAL


class TestT17Boundaries:
    def test_symlink_escape_invalid(self, tmp_path):
        root = _mk_pkg(tmp_path, GOOD_MANIFEST, skills={"s1": GOOD_SKILL})
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "SKILL.md").write_text(GOOD_SKILL)
        (root / "skills" / "linked").symlink_to(outside)
        r = parse_plugin_package(root)
        linked = [s for s in r.skills if s.name == "linked"]
        assert linked and linked[0].status == STATUS_INVALID
        assert "escapes" in linked[0].reason

    def test_stdio_missing_command_needs_config(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            mcp={"mcpServers": {"c": {"type": "stdio"}}},
        )
        r = parse_plugin_package(root)
        assert r.servers[0].status == STATUS_NEEDS_CONFIG

    def test_http_missing_url_needs_config(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            mcp={"mcpServers": {"h": {"type": "http"}}},
        )
        r = parse_plugin_package(root)
        assert r.servers[0].status == STATUS_NEEDS_CONFIG

    def test_unrecognized_placeholder_needs_config(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            mcp={"mcpServers": {
                "c": {"type": "stdio", "command": "x",
                      "args": ["${PLUGIN_CODE}"]}
            }},
        )
        r = parse_plugin_package(root)
        assert r.servers[0].status == STATUS_NEEDS_CONFIG
        assert "PLUGIN_CODE" in r.servers[0].reason

    def test_recognized_placeholder_supported(self):
        r = parse_plugin_package(FIXTURE)
        echo = [s for s in r.servers if s.name == "echo"][0]
        assert echo.status == STATUS_SUPPORTED
        assert echo.command[0] == "echo"


class TestCapAndOverall:
    def test_component_cap_truncates(self, tmp_path):
        servers = {
            f"s{i}": {"type": "stdio", "command": "echo"} for i in range(MAX_COMPONENTS + 5)
        }
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            skills={"s1": GOOD_SKILL},
            mcp={"mcpServers": servers},
        )
        r = parse_plugin_package(root)
        total = len(r.skills) + len(r.servers)
        assert total == MAX_COMPONENTS
        assert any("truncated" in w for w in r.warnings)

    def test_all_unsupported_overall_unavailable(self, tmp_path):
        root = _mk_pkg(
            tmp_path,
            GOOD_MANIFEST,
            mcp={"mcpServers": {"w": {"type": "weird"}}},
        )
        assert parse_plugin_package(root).overall == PACKAGE_UNAVAILABLE

    def test_report_as_dict_shape(self):
        d = parse_plugin_package(FIXTURE).as_dict()
        assert set(d) == {
            "plugin_name", "version", "overall", "root",
            "skills", "servers", "warnings",
        }
        assert d["plugin_name"] == "demo-plugin"
