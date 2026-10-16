"""extensions/store 单测（DESIGN-20261009 P1-A: T19 CAS / T21 PLUGIN_DATA / §13 记录卫生）."""

import json
from pathlib import Path

import pytest

from llm_loop.extensions.store import (
    ExtensionStore,
    InstallRejectedError,
    RevisionConflictError,
    _scan_sensitive,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "std_plugin_demo"


@pytest.fixture()
def store(tmp_path):
    return ExtensionStore(tmp_path / "extensions")


def _write_pkg(root: Path, version="0.1.0", skill_body="# v\n"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(json.dumps({
        "name": "demo-plugin", "schema_version": "1.0.0", "version": version,
    }))
    s = root / "skills" / "deploy"
    s.mkdir(parents=True, exist_ok=True)
    (s / "SKILL.md").write_text(
        f"---\nname: deploy\ndescription: d\n---\n{skill_body}"
    )


class TestInstall:
    def test_install_creates_record_and_layout(self, store, tmp_path):
        _write_pkg(tmp_path / "pkg")
        rec = store.install(
            tmp_path / "pkg", source="local", expected_revision=0
        )
        assert rec.install_id == "demo-plugin"
        state = store.read_state()
        assert state.revision == 1
        assert len(state.installs) == 1
        assert store.package_root(rec.digest).is_dir()
        assert (store.instance_data_dir(rec.install_id) / "").exists()
        data = json.loads((store.root / "installed.json").read_text())
        assert data["revision"] == 1
        comp = {(c.kind, c.name): c for c in rec.components}
        assert ("skill", "deploy") in comp

    def test_install_unavailable_rejected(self, store, tmp_path):
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "plugin.json").write_text("{nope")
        with pytest.raises(InstallRejectedError):
            store.install(bad, source="local", expected_revision=0)

    def test_fixture_install(self, store):
        rec = store.install(FIXTURE, source="fixture", expected_revision=0)
        assert rec.plugin_name == "demo-plugin"
        assert len(rec.components) == 3  # 2 skills + 1 server
        assert store.read_state().revision == 1


class TestT19CAS:
    def test_late_writer_with_stale_revision_fails(self, store, tmp_path):
        _write_pkg(tmp_path / "pkg")
        store.install(tmp_path / "pkg", source="a", expected_revision=0)
        # 第二写者持有过期 revision=0 → 冲突失败（§9.1）
        with pytest.raises(RevisionConflictError):
            store.install(
                tmp_path / "pkg", source="a", expected_revision=0
            )

    def test_sequential_writer_with_fresh_revision_succeeds(
        self, store, tmp_path
    ):
        _write_pkg(tmp_path / "pkg")
        store.install(tmp_path / "pkg", source="a", expected_revision=0)
        rec = store.set_enabled(
            "demo-plugin", enabled=False, expected_revision=1
        )
        assert store.read_state().revision == 2
        assert all(not c.enabled for c in rec.components)

    def test_uninstall_cas(self, store, tmp_path):
        _write_pkg(tmp_path / "pkg")
        store.install(tmp_path / "pkg", source="a", expected_revision=0)
        with pytest.raises(RevisionConflictError):
            store.uninstall("demo-plugin", expected_revision=0)
        assert store.uninstall("demo-plugin", expected_revision=1) == "demo-plugin"
        assert store.read_state().installs == ()
        # 包副本与实例数据保留（不可变审计 + 不自动回滚）
        assert list((store.root / "packages").iterdir())
        assert store.instance_data_dir("demo-plugin").exists()

    def test_unknown_install_rejected(self, store):
        with pytest.raises(InstallRejectedError):
            store.set_enabled("ghost", enabled=True, expected_revision=0)


class TestT21PluginData:
    def test_data_survives_version_update(self, store, tmp_path):
        _write_pkg(tmp_path / "v1", version="0.1.0", skill_body="# v1")
        rec1 = store.install(tmp_path / "v1", source="s", expected_revision=0)
        data_file = store.instance_data_dir(rec1.install_id) / "state.txt"
        data_file.write_text("persist-me")
        # 新版本（digest 变化）→ 同一安装更新
        _write_pkg(tmp_path / "v2", version="0.2.0", skill_body="# v2 changed")
        rec2 = store.install(tmp_path / "v2", source="s", expected_revision=1)
        assert rec2.install_id == rec1.install_id
        assert rec2.digest != rec1.digest
        assert rec2.version == "0.2.0"
        assert data_file.read_text() == "persist-me"  # PLUGIN_DATA 保留
        state = store.read_state()
        assert len(state.installs) == 1

    def test_same_source_reinstall_updates_record(self, store, tmp_path):
        _write_pkg(tmp_path / "pkg")
        r1 = store.install(tmp_path / "pkg", source="s", expected_revision=0)
        r2 = store.install(tmp_path / "pkg", source="s", expected_revision=1)
        assert r1.install_id == r2.install_id
        assert r2.digest == r1.digest
        assert store.read_state().revision == 2

    def test_different_source_conflict_rejected(self, store, tmp_path):
        _write_pkg(tmp_path / "pkg")
        store.install(tmp_path / "pkg", source="a", expected_revision=0)
        with pytest.raises(InstallRejectedError, match="different source"):
            store.install(tmp_path / "pkg", source="b", expected_revision=1)


class TestUpdateEnablement:
    @pytest.mark.parametrize("version", ["0.1.0", "0.2.0"])
    def test_update_preserves_component_disable(self, store, tmp_path, version):
        root = tmp_path / "pkg"
        _write_pkg(root)
        (root / "mcp.json").write_text(json.dumps({
            "mcpServers": {"echo": {"type": "stdio", "command": "echo"}},
        }))
        store.install(root, source="local", expected_revision=0)
        store.set_enabled("demo-plugin", component="deploy", enabled=False,
                          expected_revision=1)
        _write_pkg(root, version=version)
        updated = store.install(root, source="local", expected_revision=2)
        states = {(c.kind, c.name): c.enabled for c in updated.components}
        assert states[("skill", "deploy")] is False
        assert states[("mcp_server", "echo")] is True
        assert store.read_state().installs[0] == updated

    def test_disabled_install_stays_disabled_when_update_adds_component(self, store, tmp_path):
        root = tmp_path / "pkg"
        _write_pkg(root)
        store.install(root, source="local", expected_revision=0)
        store.set_enabled("demo-plugin", enabled=False, expected_revision=1)
        _write_pkg(root, version="0.2.0")
        new_skill = root / "skills" / "inspect"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text(
            "---\nname: inspect\ndescription: inspect\n---\n# Inspect\n"
        )
        updated = store.install(root, source="local", expected_revision=2)
        assert len(updated.components) == 2
        assert all(not c.enabled for c in updated.components)

    def test_new_component_does_not_inherit_other_kind_disable(self, store, tmp_path):
        root = tmp_path / "pkg"
        _write_pkg(root)
        mcp = root / "mcp.json"
        mcp.write_text(json.dumps({
            "mcpServers": {"echo": {"type": "stdio", "command": "echo"}},
        }))
        store.install(root, source="local", expected_revision=0)
        store.set_enabled("demo-plugin", component="deploy", enabled=False,
                          expected_revision=1)
        mcp.write_text(json.dumps({
            "mcpServers": {"deploy": {"type": "stdio", "command": "echo"}},
        }))
        updated = store.install(root, source="local", expected_revision=2)
        states = {(c.kind, c.name): c.enabled for c in updated.components}
        assert states[("skill", "deploy")] is False
        assert states[("mcp_server", "deploy")] is True


class TestRecordHygiene:
    def test_scan_sensitive_catches_tokens(self):
        assert _scan_sensitive({"env": {"api_token": "x"}})
        assert _scan_sensitive({"headers": {"Authorization": "Bearer y"}})
        assert _scan_sensitive([{"password": "p"}])
        assert not _scan_sensitive({"command": "echo", "args": ["hi"]})

    def test_record_has_no_env_or_headers(self, store, tmp_path):
        _write_pkg(tmp_path / "pkg")
        (tmp_path / "pkg" / "mcp.json").write_text(json.dumps({
            "mcpServers": {"s": {
                "type": "stdio", "command": "x",
                "env": {"TOKEN": "secret"},
            }}
        }))
        rec = store.install(tmp_path / "pkg", source="s", expected_revision=0)
        blob = json.dumps(rec.as_dict())
        assert "TOKEN" not in blob
        assert "secret" not in blob

    def test_corrupted_state_rejected_on_read(self, store):
        store.state_file.write_text("{corrupt")
        with pytest.raises(InstallRejectedError):
            store.read_state()
